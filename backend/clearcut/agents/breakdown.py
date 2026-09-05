"""
Agent 1 — Breakdown.

The clearance analogue of the 1st AD's script breakdown. Where the AD marks
cast, props and stunts, this marks everything that carries legal exposure.

Extraction runs per scene rather than over the whole script: it keeps the
model's attention narrow, makes scene and page attribution exact instead of
inferred, and lets scenes be processed concurrently.
"""

from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from pydantic import BaseModel, Field

from clearcut.agents.depiction import DepictionAgent
from clearcut.core.coalesce import coalesce
from clearcut.core.naming import merge_key
from clearcut.core.models import (
    AgentEvent,
    ClearableItem,
    ClearanceCategory,
    ScriptLocation,
)
from clearcut.core.screenplay import ParsedScreenplay, Scene
from clearcut.services.gemini_client import get_gemini

logger = logging.getLogger(__name__)

EmitFn = Callable[[AgentEvent], None]

SYSTEM = """You are a script clearance researcher at a motion picture clearance house.
You prepare the report an Errors & Omissions insurance carrier requires before it
will bind coverage on a production.

Your job is to mark every element in a scene that carries legal exposure. You are
deliberately over-inclusive: a missed item becomes an uninsurable film, while a
false positive costs only a few minutes of review.

MARK these categories:
- character_name: every named character (first, last or full). Villains matter most.
- business_name: any company or trade name spoken or seen
- brand_product: any real consumer brand or product
- phone_number: every phone number
- address: every street address or specific premises
- license_plate: every vehicle plate
- url_domain: every website or domain
- email: every email address
- music_cue: every song title, lyric, artist or needle-drop
- artwork: paintings, photographs, posters, sculpture visible on camera
- film_tv_clip: any film or television material playing in scene
- print_media: newspapers, magazines, mastheads
- logo_signage: visible logos or signage
- real_person: any reference to an actual living or recently deceased person
- organization: real institutions, hospitals, agencies, insurers, universities
- location_name: named real venues
- depiction_risk: any entity shown committing crime, fraud or misconduct

RULES:
- Quote the text VERBATIM as it appears. Never paraphrase the quote.
- One entry per distinct subject. If a name appears three times in the scene, return it once.
- Set is_depicted_negatively=true when the subject is shown committing or enabling
  wrongdoing, or is portrayed in a way its owner would object to. This drives
  defamation and trademark tarnishment analysis downstream.
- context: one short line on how the item is used in the scene.
- Do NOT mark generic nouns, common objects, or fictional-sounding words with no
  real-world referent risk. Do not mark the protagonist's emotions or actions.
"""


class _Extracted(BaseModel):
    value: str = Field(description="Normalised subject, e.g. 'Halloran Freight'")
    category: str = Field(description="One of the listed category ids")
    quote: str = Field(description="Verbatim text from the scene")
    context: str = Field(default="", description="How it is used in the scene")
    is_depicted_negatively: bool = False


class BreakdownAgent:
    name = "breakdown"

    def __init__(self, emit: EmitFn | None = None, max_workers: int = 2):
        self._emit = emit or (lambda e: None)
        self._max_workers = max_workers

    def run(self, script: ParsedScreenplay) -> list[ClearableItem]:
        self._emit(
            AgentEvent(
                agent=self.name,
                phase="start",
                message=f"Breaking down {len(script.scenes)} scenes across {script.total_pages} pages",
                payload={"scenes": len(script.scenes), "pages": script.total_pages},
            )
        )

        results: list[tuple[Scene, list[_Extracted]]] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            for scene, found in pool.map(self._scene_pair, script.scenes):
                results.append((scene, found))

        raw_items = self._merge(results)
        items, notes = coalesce(raw_items)

        # Scene-parallel extraction cannot see how the script as a whole treats a
        # subject, and depiction decides half of every clearance ruling. Re-judge
        # it globally now that the subject list is settled.
        items = DepictionAgent(emit=self._emit).run(script, items)

        folded = len(raw_items) - len(items)
        if folded:
            self._emit(
                AgentEvent(
                    agent=self.name,
                    phase="coalesce",
                    message=f"Coalesced {folded} duplicate/fragment items",
                    payload={"folded": folded, "notes": notes},
                )
            )

        self._emit(
            AgentEvent(
                agent=self.name,
                phase="done",
                message=f"Flagged {len(items)} clearable items",
                payload={"items": len(items)},
            )
        )
        return items

    # ------------------------------------------------------------------ #
    def _scene_pair(self, scene: Scene) -> tuple[Scene, list[_Extracted]]:
        return scene, self._extract_scene(scene)

    def _extract_scene(self, scene: Scene) -> list[_Extracted]:
        prompt = (
            f"SCENE {scene.scene_number or scene.index} "
            f"(screenplay pages {scene.start_page}-{scene.end_page})\n"
            f"{'-' * 60}\n{scene.text}\n{'-' * 60}\n\n"
            "Return every clearable element in this scene."
        )
        try:
            raw = get_gemini().generate_structured(
                prompt=prompt,
                schema=list[_Extracted],
                system=SYSTEM,
                temperature=0.0,
                thinking_budget=0,
            )
        except Exception as exc:  # noqa: BLE001 — one bad scene must not sink the run
            logger.warning("Breakdown failed on scene %s: %s", scene.index, exc)
            self._emit(
                AgentEvent(
                    agent=self.name, phase="error",
                    message=f"Scene {scene.index} extraction failed: {exc}",
                )
            )
            return []

        out: list[_Extracted] = []
        for row in raw or []:
            try:
                out.append(_Extracted.model_validate(row))
            except Exception:  # noqa: BLE001, S112
                continue

        self._emit(
            AgentEvent(
                agent=self.name, phase="scene",
                message=f"Scene {scene.index} ({scene.heading[:44]}): {len(out)} items",
                payload={"scene": scene.index, "count": len(out)},
            )
        )
        return out

    # ------------------------------------------------------------------ #
    def _merge(self, results: list[tuple[Scene, list[_Extracted]]]) -> list[ClearableItem]:
        """Collapse repeats of the same subject into one item with many locations."""
        merged: dict[str, ClearableItem] = {}

        for scene, found in results:
            for ex in found:
                category = _coerce_category(ex.category)
                if category is None:
                    continue
                key = f"{category.value}::{merge_key(ex.value)}"
                loc = ScriptLocation(
                    page=scene.start_page,
                    scene_number=scene.scene_number or str(scene.index),
                    scene_heading=scene.heading,
                    quote=ex.quote.strip()[:300],
                )
                if key in merged:
                    item = merged[key]
                    item.locations.append(loc)
                    # Negative depiction anywhere taints the whole item.
                    item.is_depicted_negatively |= ex.is_depicted_negatively
                else:
                    merged[key] = ClearableItem(
                        id="itm_" + hashlib.sha1(key.encode()).hexdigest()[:10],
                        category=category,
                        value=ex.value.strip(),
                        locations=[loc],
                        context=ex.context.strip() or None,
                        is_depicted_negatively=ex.is_depicted_negatively,
                    )

        return sorted(
            merged.values(),
            key=lambda i: (i.locations[0].page, i.category.value, i.value.lower()),
        )



def _coerce_category(raw: str) -> ClearanceCategory | None:
    key = re.sub(r"[^a-z_]", "", raw.lower().strip().replace(" ", "_"))
    try:
        return ClearanceCategory(key)
    except ValueError:
        aliases = {
            "brand": ClearanceCategory.BRAND_PRODUCT,
            "product": ClearanceCategory.BRAND_PRODUCT,
            "company": ClearanceCategory.BUSINESS_NAME,
            "song": ClearanceCategory.MUSIC_CUE,
            "music": ClearanceCategory.MUSIC_CUE,
            "person": ClearanceCategory.REAL_PERSON,
            "character": ClearanceCategory.CHARACTER_NAME,
            "url": ClearanceCategory.URL_DOMAIN,
            "domain": ClearanceCategory.URL_DOMAIN,
            "newspaper": ClearanceCategory.PRINT_MEDIA,
            "institution": ClearanceCategory.ORGANIZATION,
            "location": ClearanceCategory.LOCATION_NAME,
        }
        return aliases.get(key)
