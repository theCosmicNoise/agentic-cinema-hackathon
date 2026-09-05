"""
Reconciling rulings that contradict each other.

A clearance report is read by an insurer's counsel, and an internal
contradiction in it is indefensible whichever half is right. The run that
prompted this cleared voss@zenithmotors.com while ruling zenithmotors.com,
its own domain, must_change. Both rulings were reached honestly: the email
standard asks whether a real mailbox could receive viewer mail, the domain
standard asks who the registrant is, and nothing looked at both.

So related subjects are reconciled after adjudication, by rule rather than by
another model call. The rule is always to adopt the stricter of the two, for
the same reason the rest of the pipeline over-flags: a contradiction resolved
downward is a risk that reaches the finished film.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from clearcut.core.models import Adjudication, ClearableItem, ClearanceCategory, Verdict

# Ordered least to most restrictive. Reconciliation always moves up this list.
_SEVERITY = [
    Verdict.CLEAR,
    Verdict.CLEAR_WITH_CAUTION,
    Verdict.LEGAL_REVIEW,
    Verdict.LICENSE_REQUIRED,
    Verdict.MUST_CHANGE,
]
_RANK = {v: i for i, v in enumerate(_SEVERITY)}


@dataclass
class Reconciliation:
    item_id: str
    value: str
    was: Verdict
    now: Verdict
    because: str


def _domain_of(value: str) -> str | None:
    """The registrable domain in an email address or URL, if there is one."""
    v = value.strip().lower()
    if "@" in v:
        v = v.rsplit("@", 1)[-1]
    v = re.sub(r"^(https?://)?(www\.)?", "", v).split("/")[0].strip()
    return v if "." in v and " " not in v else None


def reconcile(
    items: list[ClearableItem], rulings: dict[str, Adjudication]
) -> list[Reconciliation]:
    """Raise any ruling that a related subject contradicts. Mutates `rulings`."""
    # Strictest verdict seen for each domain, across emails and URLs alike.
    strictest: dict[str, tuple[Verdict, str]] = {}
    for it in items:
        if it.category not in (ClearanceCategory.EMAIL, ClearanceCategory.URL_DOMAIN):
            continue
        adj = rulings.get(it.id)
        dom = _domain_of(it.value)
        if not (adj and dom):
            continue
        held = strictest.get(dom)
        if held is None or _RANK[adj.verdict] > _RANK[held[0]]:
            strictest[dom] = (adj.verdict, it.value)

    changes: list[Reconciliation] = []
    for it in items:
        if it.category not in (ClearanceCategory.EMAIL, ClearanceCategory.URL_DOMAIN):
            continue
        adj = rulings.get(it.id)
        dom = _domain_of(it.value)
        if not (adj and dom and dom in strictest):
            continue
        top, source = strictest[dom]
        if source == it.value or _RANK[top] <= _RANK[adj.verdict]:
            continue

        because = (
            f"Raised to match '{source}', which shares the domain {dom} and was "
            f"ruled {top.value.replace('_', ' ')}. A report cannot clear an address "
            f"on a domain it separately says must change."
        )
        changes.append(Reconciliation(it.id, it.value, adj.verdict, top, because))
        rulings[it.id] = adj.model_copy(
            update={
                "verdict": top,
                "rule_applied": "RECONCILED_WITH_RELATED_SUBJECT",
                "rationale": adj.rationale.rstrip(". ") + ". " + because,
            }
        )
    return changes
