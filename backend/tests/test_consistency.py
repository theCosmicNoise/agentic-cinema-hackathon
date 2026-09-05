"""
Reconciliation tests.

The rule has to move in one direction only. A pass that could lower a ruling
would let a contradiction be resolved into a risk reaching the finished film,
so the tests pin the direction as hard as the behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clearcut.core.consistency import _domain_of, reconcile
from clearcut.core.models import (
    Adjudication,
    ClearableItem,
    ClearanceCategory,
    RiskLevel,
    ScriptLocation,
    Verdict,
)


def _item(value, category, iid):
    return ClearableItem(
        id=iid, category=category, value=value,
        locations=[ScriptLocation(page=1, scene_number="1", quote=value)],
    )


def _adj(iid, verdict):
    return Adjudication(
        item_id=iid, verdict=verdict, risk=RiskLevel.LOW, rationale="ruled."
    )


def test_email_is_raised_to_match_its_own_domain():
    """The case that prompted this: an address cleared on a domain that must change."""
    items = [
        _item("voss@zenithmotors.com", ClearanceCategory.EMAIL, "e1"),
        _item("zenithmotors.com", ClearanceCategory.URL_DOMAIN, "d1"),
    ]
    rulings = {"e1": _adj("e1", Verdict.CLEAR), "d1": _adj("d1", Verdict.MUST_CHANGE)}

    changes = reconcile(items, rulings)

    assert rulings["e1"].verdict is Verdict.MUST_CHANGE
    assert rulings["d1"].verdict is Verdict.MUST_CHANGE, "the stricter one is untouched"
    assert len(changes) == 1
    assert changes[0].was is Verdict.CLEAR
    assert "zenithmotors.com" in changes[0].because


def test_never_lowers_a_ruling():
    """A cleared sibling must not drag a must_change down."""
    items = [
        _item("hello@example.com", ClearanceCategory.EMAIL, "e1"),
        _item("example.com", ClearanceCategory.URL_DOMAIN, "d1"),
    ]
    rulings = {"e1": _adj("e1", Verdict.MUST_CHANGE), "d1": _adj("d1", Verdict.CLEAR)}

    reconcile(items, rulings)

    assert rulings["e1"].verdict is Verdict.MUST_CHANGE
    assert rulings["d1"].verdict is Verdict.MUST_CHANGE, "raised to match the address"


def test_unrelated_domains_are_left_alone():
    items = [
        _item("a@one.com", ClearanceCategory.EMAIL, "e1"),
        _item("two.com", ClearanceCategory.URL_DOMAIN, "d1"),
    ]
    rulings = {"e1": _adj("e1", Verdict.CLEAR), "d1": _adj("d1", Verdict.MUST_CHANGE)}

    assert reconcile(items, rulings) == []
    assert rulings["e1"].verdict is Verdict.CLEAR


def test_severity_order_is_respected():
    """license_required outranks legal_review, which outranks clear_with_caution."""
    items = [
        _item("a@x.com", ClearanceCategory.EMAIL, "e1"),
        _item("x.com", ClearanceCategory.URL_DOMAIN, "d1"),
    ]
    rulings = {
        "e1": _adj("e1", Verdict.CLEAR_WITH_CAUTION),
        "d1": _adj("d1", Verdict.LEGAL_REVIEW),
    }
    reconcile(items, rulings)
    assert rulings["e1"].verdict is Verdict.LEGAL_REVIEW


def test_other_categories_are_untouched():
    """Only addresses and domains share a referent this way."""
    items = [
        _item("Zenith Motors", ClearanceCategory.BUSINESS_NAME, "b1"),
        _item("zenithmotors.com", ClearanceCategory.URL_DOMAIN, "d1"),
    ]
    rulings = {"b1": _adj("b1", Verdict.CLEAR), "d1": _adj("d1", Verdict.MUST_CHANGE)}

    assert reconcile(items, rulings) == []
    assert rulings["b1"].verdict is Verdict.CLEAR


def test_domain_extraction():
    assert _domain_of("voss@zenithmotors.com") == "zenithmotors.com"
    assert _domain_of("https://www.Example.com/path") == "example.com"
    assert _domain_of("midwestsalvageauth.com") == "midwestsalvageauth.com"
    assert _domain_of("not a domain") is None
    assert _domain_of("Zenith Motors") is None


# --------------------------------------------------------------------------- #
# Licence plates
# --------------------------------------------------------------------------- #
def test_plate_is_never_cleared_by_absence_of_evidence():
    """Ten runs out of ten cleared a plate because no search can ever find one.

    Registration records are not public, so a lookup returns nothing for every
    plate, invented or issued. Silence is not evidence, and this is settled by
    rule rather than research.
    """
    from clearcut.core.rules import RESEARCH_REQUIRED, apply_deterministic_rule

    for plate in ("KJ-4471", "4KJ-882", "ABC 1234", "7XYZ123"):
        outcome = apply_deterministic_rule(ClearanceCategory.LICENSE_PLATE, plate)
        assert outcome is not None, f"{plate} fell through to research"
        assert outcome.verdict is Verdict.MUST_CHANGE
        assert outcome.rule_id == "PLATE_NOT_SEARCHABLE"

    assert ClearanceCategory.LICENSE_PLATE not in RESEARCH_REQUIRED, (
        "a plate lookup always comes back empty, so it must not spend one"
    )
