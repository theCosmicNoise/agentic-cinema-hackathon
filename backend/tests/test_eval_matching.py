"""
Eval matcher tests.

The harness decides which found subject answers which planted one. Get that
wrong and it reports failures that never happened, which is worse than no
measurement at all because it sends you fixing things that work.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clearcut.core.models import ClearableItem, ClearanceCategory, ScriptLocation, Verdict
from clearcut.evals.harness import match_score, score


def _item(value, category, iid):
    return ClearableItem(
        id=iid, category=category, value=value,
        locations=[ScriptLocation(page=1, scene_number="1", quote=value)],
    )


def test_containment_beats_shared_token():
    """The bug: 'voss@zenithmotors.com' matched the character 'Cortland Voss'."""
    email_to_char = match_score("voss@zenithmotors.com", "Cortland Voss")
    email_to_email = match_score("voss@zenithmotors.com", "voss@zenithmotors.com")
    assert email_to_email > email_to_char


def test_assignment_does_not_cross_pair():
    truth = {
        "script": "t",
        "planted_items": [
            {"value": "voss@zenithmotors.com", "category": "email",
             "expected_verdict": "must_change"},
            {"value": "CORTLAND VOSS", "category": "character_name",
             "expected_verdict": "clear"},
        ],
    }
    items = [
        _item("Cortland Voss", ClearanceCategory.CHARACTER_NAME, "c1"),
        _item("voss@zenithmotors.com", ClearanceCategory.EMAIL, "e1"),
    ]
    rulings = {"c1": Verdict.CLEAR, "e1": Verdict.MUST_CHANGE}

    res = score(truth, items, rulings)
    by_name = {i.expected: i for i in res.items}

    assert by_name["voss@zenithmotors.com"].found_as == "voss@zenithmotors.com"
    assert by_name["CORTLAND VOSS"].found_as == "Cortland Voss"
    assert res.verdict_agreement == 1.0, "both agree once matched correctly"


def test_partial_name_still_matches():
    """'NIGHTHAWKS' legitimately answers 'Edward Hopper NIGHTHAWKS'."""
    truth = {"script": "t", "planted_items": [
        {"value": "Edward Hopper NIGHTHAWKS", "category": "artwork"}]}
    items = [_item("NIGHTHAWKS", ClearanceCategory.ARTWORK, "a1")]
    assert score(truth, items).recall == 1.0


def test_category_disagreement_is_penalised_not_fatal():
    assert match_score("Zenith Motors", "Zenith Motors", "business_name", "logo_signage") > 20
    assert (match_score("Zenith Motors", "Zenith Motors", "business_name", "business_name")
            > match_score("Zenith Motors", "Zenith Motors", "business_name", "logo_signage"))


def test_unrelated_subjects_do_not_match():
    assert match_score("Coca-Cola", "Chicago Tribune") == 0.0
