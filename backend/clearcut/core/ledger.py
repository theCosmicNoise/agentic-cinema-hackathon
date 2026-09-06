"""
The clearance ledger — persistent state across the life of a production.

This is the wedge. Today a clearance report is a dead document: it describes one
draft, and the moment pink pages ship it is stale. Productions either re-buy the
whole report or, far more often, shoot uncleared pages and hope.

The ledger makes clearance a state the production continuously holds. On a new
draft, only the delta is re-cleared.

The subtlety that makes this correct rather than merely fast: a verdict is a
function of the subject AND how the script treats it. STATE FARM mentioned in
passing and STATE FARM shown approving fraudulent claims are the same nine
characters and completely different clearance outcomes. So an entry is only
reusable when the value, the category AND the depiction are all unchanged.
Reusing on the name alone would silently pass a defamation claim through a
revision, which is exactly the failure this product exists to prevent.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from clearcut.core.blobs import LocalBlobs, get_blobs
from clearcut.core.config import get_settings
from clearcut.core.models import (
    Adjudication,
    ClearableItem,
    LedgerEntry,
    RevisionDiff,
)

logger = logging.getLogger(__name__)


def item_key(item: ClearableItem) -> str:
    """Stable identity for a clearance subject across drafts."""
    norm = re.sub(r"[^a-z0-9]+", " ", item.value.lower()).strip()
    return f"{item.category.value}::{norm}"


def _depiction_key(item: ClearableItem) -> str:
    """The part of the context a verdict actually turns on."""
    return "negative" if item.is_depicted_negatively else "neutral"


class ClearanceLedger:
    """Per-project clearance state, persisted as JSON."""

    def __init__(self, project_id: str, root: Path | None = None, store=None):
        """`root` keeps the old call sites working and scopes local storage.

        Passing `store` overrides both, which is how tests stay isolated from
        each other and from whatever this deployment is really writing to.
        """
        self.project_id = project_id
        # Keyed rather than pathed, so the same ledger works on a local disk
        # and in a bucket without the caller knowing which.
        self.key = f"ledger/{project_id}.json"
        if store is not None:
            self._blobs = store
        elif root is not None and not get_settings().bucket:
            # An explicit root with no bucket configured means local, and means
            # that root rather than the process-wide default.
            self._blobs = LocalBlobs(Path(root))
        else:
            self._blobs = get_blobs()
        self.entries: dict[str, LedgerEntry] = {}
        self._depiction: dict[str, str] = {}
        self.history: list[dict] = []
        self._load()

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        raw = self._blobs.read(self.key)
        if raw is None:
            return
        try:
            blob = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Ledger unreadable, starting fresh: %s", exc)
            return
        for k, entry in (blob.get("entries") or {}).items():
            try:
                self.entries[k] = LedgerEntry.model_validate(entry)
            except Exception:  # noqa: BLE001, S112
                continue
        self._depiction = blob.get("depiction") or {}
        self.history = blob.get("history") or []

    def save(self) -> None:
        blob = {
            "project_id": self.project_id,
            "entries": {k: v.model_dump(mode="json") for k, v in self.entries.items()},
            "depiction": self._depiction,
            "history": self.history,
        }
        self._blobs.write(self.key, json.dumps(blob, indent=2, default=str))

    # ------------------------------------------------------------------ #
    def plan_revision(
        self, items: list[ClearableItem], draft_label: str
    ) -> tuple[list[ClearableItem], dict[str, LedgerEntry], RevisionDiff]:
        """Split a new draft's items into what must be re-cleared and what carries over.

        Returns (to_clear, reusable_entries_by_item_id, diff).
        """
        to_clear: list[ClearableItem] = []
        reusable: dict[str, LedgerEntry] = {}
        added: list[str] = []
        unchanged: list[str] = []

        seen_keys: set[str] = set()

        for item in items:
            key = item_key(item)
            seen_keys.add(key)
            entry = self.entries.get(key)

            if entry is None:
                to_clear.append(item)
                added.append(item.value)
                continue

            # Same subject, but the script now treats it differently — the
            # earlier verdict does not transfer.
            if self._depiction.get(key) != _depiction_key(item):
                to_clear.append(item)
                added.append(f"{item.value} (depiction changed)")
                continue

            reusable[item.id] = entry
            unchanged.append(item.value)

        removed = [
            e.value for k, e in self.entries.items() if k not in seen_keys
        ]

        prior = self.history[-1]["draft"] if self.history else None
        diff = RevisionDiff(
            from_draft=prior,
            to_draft=draft_label,
            added=added,
            removed=removed,
            unchanged=unchanged,
        )
        return to_clear, reusable, diff

    def record(
        self,
        items: list[ClearableItem],
        rulings: dict[str, Adjudication],
        draft_label: str,
    ) -> None:
        """Commit this draft's rulings into the ledger."""
        now = datetime.now(timezone.utc)
        for item in items:
            adj = rulings.get(item.id)
            if adj is None:
                continue
            key = item_key(item)
            existing = self.entries.get(key)
            self.entries[key] = LedgerEntry(
                item_key=key,
                category=item.category,
                value=item.value,
                verdict=adj.verdict,
                risk=adj.risk,
                rationale=adj.rationale,
                citations=adj.citations,
                first_cleared_draft=(
                    existing.first_cleared_draft if existing else draft_label
                ),
                last_verified_draft=draft_label,
                last_verified_at=now,
            )
            self._depiction[key] = _depiction_key(item)

        self.history.append(
            {
                "draft": draft_label,
                "at": now.isoformat(),
                "items": len(items),
            }
        )

    # ------------------------------------------------------------------ #
    def savings(self, diff: RevisionDiff) -> dict[str, float | int]:
        """What re-clearing only the delta avoided on this revision.

        Per-item figures are configurable estimates, not quoted prices — the
        honest unit here is items and lookups avoided.
        """
        reused = len(diff.unchanged)
        return {
            "items_reused": reused,
            "items_recleared": len(diff.added),
            "reuse_ratio": diff.reuse_ratio,
            "research_calls_avoided": reused,
        }
