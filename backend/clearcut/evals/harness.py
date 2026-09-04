"""
Measuring whether the clearance is any good.

Four numbers matter, and they are not equally important.

Recall is the one that decides whether the product is safe to sell. A missed
subject never reaches a reviewer, never appears in the report, and shows up
later as an uninsurable film. A false positive costs somebody thirty seconds.
So recall is reported first and a miss is treated as a failure, while extra
flags are reported separately as review load rather than as errors.

Depiction accuracy sits just behind it, because half of every ruling turns on
how the script treats a subject, and getting that wrong flips a defamation risk
into a CLEAR.

Verdict agreement is reported last and deliberately not called accuracy. The
expected verdicts are one experienced reading of standard practice, not ground
truth in the physical sense, and where the system and the target disagree the
target is sometimes the one that is wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clearcut.core.models import ClearableItem, Verdict


def _norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", str(s).lower())
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split() if len(t) > 3}


def matches(expected: str, found: str) -> bool:
    """Whether a found subject is the planted one.

    Deliberately generous on surface form: the fixture writes
    'Edward Hopper NIGHTHAWKS' and the agent returns 'Nighthawks'. Both name the
    same subject and counting that as a miss would measure formatting, not
    clearance.
    """
    e, f = _norm(expected), _norm(found)
    if e == f or e in f or f in e:
        return True
    te, tf = _tokens(expected), _tokens(found)
    return bool(te and tf and (te & tf))


@dataclass
class ItemResult:
    expected: str
    category: str
    found_as: str | None = None
    expected_verdict: str | None = None
    actual_verdict: str | None = None
    expected_negative: bool | None = None
    actual_negative: bool | None = None

    @property
    def recalled(self) -> bool:
        return self.found_as is not None

    @property
    def verdict_agrees(self) -> bool | None:
        if not (self.expected_verdict and self.actual_verdict):
            return None
        return self.expected_verdict == self.actual_verdict

    @property
    def depiction_agrees(self) -> bool | None:
        if self.expected_negative is None or self.actual_negative is None:
            return None
        return self.expected_negative == self.actual_negative


@dataclass
class EvalResult:
    fixture: str
    items: list[ItemResult] = field(default_factory=list)
    extra_flags: list[str] = field(default_factory=list)
    total_found: int = 0

    # -- recall: the number that decides whether this is safe to sell ------ #
    @property
    def recalled(self) -> int:
        return sum(1 for i in self.items if i.recalled)

    @property
    def recall(self) -> float:
        return self.recalled / len(self.items) if self.items else 0.0

    @property
    def misses(self) -> list[ItemResult]:
        return [i for i in self.items if not i.recalled]

    # -- depiction -------------------------------------------------------- #
    @property
    def depiction_scored(self) -> list[ItemResult]:
        return [i for i in self.items if i.depiction_agrees is not None]

    @property
    def depiction_agreement(self) -> float:
        s = self.depiction_scored
        return sum(1 for i in s if i.depiction_agrees) / len(s) if s else 0.0

    # -- verdicts --------------------------------------------------------- #
    @property
    def verdict_scored(self) -> list[ItemResult]:
        return [i for i in self.items if i.verdict_agrees is not None]

    @property
    def verdict_agreement(self) -> float:
        s = self.verdict_scored
        return sum(1 for i in s if i.verdict_agrees) / len(s) if s else 0.0

    @property
    def disagreements(self) -> list[ItemResult]:
        return [i for i in self.verdict_scored if not i.verdict_agrees]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture": self.fixture,
            "planted": len(self.items),
            "recalled": self.recalled,
            "recall": round(self.recall, 3),
            "misses": [i.expected for i in self.misses],
            "total_flagged": self.total_found,
            "extra_flags": len(self.extra_flags),
            "depiction_agreement": round(self.depiction_agreement, 3),
            "depiction_scored": len(self.depiction_scored),
            "verdict_agreement": round(self.verdict_agreement, 3),
            "verdict_scored": len(self.verdict_scored),
            "disagreements": [
                {
                    "item": i.expected,
                    "expected": i.expected_verdict,
                    "actual": i.actual_verdict,
                }
                for i in self.disagreements
            ],
        }


def load_truth(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def score(
    truth: dict[str, Any],
    items: list[ClearableItem],
    rulings: dict[str, Verdict] | None = None,
) -> EvalResult:
    """Score a run against a fixture's planted items."""
    res = EvalResult(fixture=truth.get("script", "?"), total_found=len(items))
    claimed: set[str] = set()

    for planted in truth.get("planted_items", []):
        r = ItemResult(
            expected=planted["value"],
            category=planted.get("category", ""),
            expected_verdict=planted.get("expected_verdict"),
            expected_negative=planted.get("expected_negative"),
        )
        for it in items:
            if it.id in claimed:
                continue
            if matches(planted["value"], it.value):
                r.found_as = it.value
                r.actual_negative = it.is_depicted_negatively
                claimed.add(it.id)
                if rulings and it.id in rulings:
                    r.actual_verdict = rulings[it.id].value
                break
        res.items.append(r)

    res.extra_flags = [it.value for it in items if it.id not in claimed]
    return res


def render(res: EvalResult) -> str:
    """A report a human reads, not a metrics dump."""
    L: list[str] = []
    L.append(f"{res.fixture}")
    L.append("=" * 68)
    L.append(
        f"  RECALL              {res.recalled}/{len(res.items)}"
        f"  ({res.recall*100:.0f}%)   <- a miss is an uninsurable film"
    )
    if res.misses:
        for m in res.misses:
            L.append(f"      MISSED  {m.expected}  [{m.category}]")
    else:
        L.append("      no planted subject was missed")

    if res.depiction_scored:
        L.append(
            f"  DEPICTION           {sum(1 for i in res.depiction_scored if i.depiction_agrees)}"
            f"/{len(res.depiction_scored)}  ({res.depiction_agreement*100:.0f}%)"
            f"   <- decides half of every ruling"
        )
        for i in res.depiction_scored:
            if not i.depiction_agrees:
                exp = "negative" if i.expected_negative else "neutral"
                act = "negative" if i.actual_negative else "neutral"
                L.append(f"      {i.expected}: expected {exp}, got {act}")

    if res.verdict_scored:
        L.append(
            f"  VERDICT AGREEMENT   {sum(1 for i in res.verdict_scored if i.verdict_agrees)}"
            f"/{len(res.verdict_scored)}  ({res.verdict_agreement*100:.0f}%)"
            f"   <- the target is one reading, not a fact"
        )
        for d in res.disagreements:
            L.append(f"      {d.expected}: expected {d.expected_verdict}, got {d.actual_verdict}")

    L.append(
        f"  REVIEW LOAD         {res.total_found} flagged, "
        f"{res.extra_flags and len(res.extra_flags) or 0} beyond the planted set"
    )
    return "\n".join(L)
