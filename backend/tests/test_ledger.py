"""
Ledger tests.

The reuse rule is the risky part of this product: reuse too eagerly and a
revision silently carries a stale verdict past a real change in exposure. These
pin the rule that an entry only transfers when the subject, its category AND
its depiction are all unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clearcut.core.ledger import ClearanceLedger, item_key
from clearcut.core.models import (
    Adjudication,
    ClearableItem,
    ClearanceCategory,
    RiskLevel,
    ScriptLocation,
    Verdict,
)


def _item(value, *, negative=False, category=ClearanceCategory.BUSINESS_NAME, iid=None):
    return ClearableItem(
        id=iid or f"itm_{abs(hash(value)) % 10**6}",
        category=category,
        value=value,
        locations=[ScriptLocation(page=1, scene_number="1", quote=value)],
        is_depicted_negatively=negative,
    )


def _ruling(item, verdict=Verdict.CLEAR):
    return Adjudication(
        item_id=item.id, verdict=verdict, risk=RiskLevel.LOW, rationale="ruled"
    )


@pytest.fixture
def ledger(tmp_path):
    return ClearanceLedger("test-project", tmp_path)


def test_first_draft_clears_everything(ledger):
    items = [_item("Zenith Motors"), _item("State Farm")]
    to_clear, reusable, diff = ledger.plan_revision(items, "White")

    assert len(to_clear) == 2
    assert reusable == {}
    assert diff.unchanged == []
    assert diff.reuse_ratio == 0.0


def test_unchanged_items_are_reused(ledger):
    items = [_item("Zenith Motors"), _item("State Farm")]
    ledger.record(items, {i.id: _ruling(i) for i in items}, "White")

    to_clear, reusable, diff = ledger.plan_revision(items, "Blue")

    assert to_clear == []
    assert len(reusable) == 2
    assert diff.reuse_ratio == 1.0


def test_new_item_in_revision_is_cleared(ledger):
    first = [_item("Zenith Motors")]
    ledger.record(first, {i.id: _ruling(i) for i in first}, "White")

    second = first + [_item("Kilbray Building", category=ClearanceCategory.ADDRESS)]
    to_clear, reusable, diff = ledger.plan_revision(second, "Blue")

    assert [i.value for i in to_clear] == ["Kilbray Building"]
    assert len(reusable) == 1
    assert diff.added == ["Kilbray Building"]


def test_depiction_change_forces_recleared_despite_same_name(ledger):
    """The rule that matters: a neutral mention turned negative must be re-cleared."""
    neutral = [_item("State Farm", negative=False)]
    ledger.record(neutral, {i.id: _ruling(i, Verdict.CLEAR) for i in neutral}, "White")

    negative = [_item("State Farm", negative=True)]
    to_clear, reusable, diff = ledger.plan_revision(negative, "Blue")

    assert [i.value for i in to_clear] == ["State Farm"]
    assert reusable == {}
    assert "State Farm (depiction changed)" in diff.added


def test_removed_item_is_reported(ledger):
    first = [_item("Zenith Motors"), _item("Delaney Building", category=ClearanceCategory.ADDRESS)]
    ledger.record(first, {i.id: _ruling(i) for i in first}, "White")

    to_clear, reusable, diff = ledger.plan_revision([first[0]], "Blue")

    assert diff.removed == ["Delaney Building"]


def test_same_name_different_category_is_a_different_subject(ledger):
    business = [_item("Delaney", category=ClearanceCategory.BUSINESS_NAME)]
    ledger.record(business, {i.id: _ruling(i) for i in business}, "White")

    address = [_item("Delaney", category=ClearanceCategory.ADDRESS)]
    to_clear, reusable, _ = ledger.plan_revision(address, "Blue")

    assert len(to_clear) == 1, "category is part of the subject's identity"


def test_item_key_is_stable_across_formatting(ledger):
    assert item_key(_item("Zenith Motors")) == item_key(_item("  zenith   motors  "))
    assert item_key(_item("Zenith Motors")) == item_key(_item("ZENITH MOTORS!"))


def test_ledger_persists_across_instances(ledger, tmp_path):
    items = [_item("Zenith Motors")]
    ledger.record(items, {i.id: _ruling(i) for i in items}, "White")
    ledger.save()

    reopened = ClearanceLedger("test-project", tmp_path)
    to_clear, reusable, _ = reopened.plan_revision(items, "Blue")

    assert to_clear == []
    assert len(reusable) == 1


def test_first_cleared_draft_is_preserved_across_revisions(ledger):
    items = [_item("Zenith Motors")]
    ledger.record(items, {i.id: _ruling(i) for i in items}, "White")
    ledger.record(items, {i.id: _ruling(i) for i in items}, "Blue")

    entry = ledger.entries[item_key(items[0])]
    assert entry.first_cleared_draft == "White"
    assert entry.last_verified_draft == "Blue"
