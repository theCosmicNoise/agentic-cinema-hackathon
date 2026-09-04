"""
Whole-script depiction pass.

Breakdown reads scenes in parallel, which is fast and accurate for *finding*
subjects but structurally blind to how the script as a whole treats them. In
THE LONG ODDS, scene 4 shows a man reading a printout with a hospital's name on
it. Read alone that is neutral. Read against scenes 3, 5 and 6 it is a forged
medical record in an insurance fraud, and the hospital is being depicted as the
source of falsified documents.

That distinction is not a detail. Exposure is the product of two things: whether
a real referent exists, and how the script treats it. Getting the second half
wrong turns a defamation risk into a CLEAR.

So depiction is decided once, globally, against the full screenplay, after the
subjects are known. One batched call rather than one per subject: the model
needs the same script in context either way, and the subjects are judged more
consistently when it sees them together.
"""

from __future__ import annotations

import logging
from typing import Callable

from pydantic import BaseModel, Field

from clearcut.core.models import AgentEvent, ClearableItem
from clearcut.core.screenplay import ParsedScreenplay
from clearcut.services.gemini_client import get_gemini

logger = logging.getLogger(__name__)

EmitFn = Callable[[AgentEvent], None]

SYSTEM = """You assess how a screenplay treats each named subject, for motion picture
clearance. You are given the full screenplay and a list of subjects found in it.

For each subject decide whether the finished film would portray it in a way its owner,
or a real person of that name, would object to.

Mark a subject NEGATIVE when the script shows it, or shows it as connected to:
- crime, fraud, forgery, conspiracy, violence, or corruption
- professional misconduct, negligence, or incompetence
- producing, carrying or authenticating falsified documents
- being the instrument or setting of wrongdoing, even passively

READ ACROSS THE WHOLE SCRIPT, not the line the subject appears on. Follow the plot to
its conclusion, then ask what each subject ends up implicated in.

Institutions and companies are the ones most often missed, so check these explicitly:
- An institution whose NAME APPEARS ON a document the script later reveals to be
  forged, falsified or fraudulent is depicted negatively. The audience is being shown
  that institution's paperwork being faked, and its owner would object. It does not
  matter that no character criticises it.
- A company is depicted negatively when it is the VEHICLE for wrongdoing: its name,
  premises, email domain or employees are used to run the scheme, even if the company
  itself is never accused.
- A person is depicted negatively when they commit wrongdoing, and ALSO when their
  identity or signature is forged or misused as part of it.

Do not require an explicit accusation. Implication through the plot is enough.

Mark NEUTRAL when the subject is set dressing, an incidental mention, or is treated
straightforwardly with no adverse implication.

Be decisive. For each subject give a one-line reason grounded in what actually happens
in the script — name the scene or the action, do not restate the category."""


class _Judgement(BaseModel):
    subject: str = Field(description="The subject exactly as given to you")
    negative: bool = Field(description="True if depicted in a way its owner would object to")
    reason: str = Field(description="One line, grounded in what happens in the script")


class DepictionAgent:
    name = "depiction"

    def __init__(self, emit: EmitFn | None = None):
        self._emit = emit or (lambda e: None)

    def run(
        self, script: ParsedScreenplay, items: list[ClearableItem]
    ) -> list[ClearableItem]:
        """Re-decide depiction for every subject against the whole screenplay."""
        if not items:
            return items

        listing = "\n".join(
            f"- {it.value}  [{it.category.value}]" for it in items
        )
        prompt = (
            f"FULL SCREENPLAY\n{'=' * 60}\n{script.raw[:120_000]}\n{'=' * 60}\n\n"
            f"SUBJECTS FOUND IN IT ({len(items)}):\n{listing}\n\n"
            f"Judge every subject listed. Return one entry per subject."
        )

        try:
            raw = get_gemini().generate_structured(
                prompt=prompt,
                schema=list[_Judgement],
                system=SYSTEM,
                temperature=0.0,
                thinking_budget=0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Depiction pass failed, keeping per-scene flags: %s", exc)
            self._emit(
                AgentEvent(
                    agent=self.name,
                    phase="error",
                    message=f"Depiction pass unavailable ({exc}); per-scene flags retained",
                )
            )
            return items

        judged: dict[str, _Judgement] = {}
        for row in raw or []:
            try:
                j = _Judgement.model_validate(row)
            except Exception:  # noqa: BLE001, S112
                continue
            judged[_key(j.subject)] = j

        changed = 0
        for it in items:
            j = judged.get(_key(it.value))
            if j is None:
                continue
            if j.negative != it.is_depicted_negatively:
                changed += 1
            # The global read supersedes the per-scene guess in both directions:
            # a scene-local flag can be a false positive just as easily.
            it.is_depicted_negatively = j.negative
            if j.negative:
                it.context = (it.context or "") + f" | Depiction: {j.reason.strip()}"

        neg = sum(1 for i in items if i.is_depicted_negatively)
        self._emit(
            AgentEvent(
                agent=self.name,
                phase="done",
                message=(
                    f"{neg} of {len(items)} subjects depicted negatively "
                    f"({changed} reassessed against the full script)"
                ),
                payload={"negative": neg, "changed": changed, "total": len(items)},
            )
        )
        return items


def _key(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "", value.lower())
