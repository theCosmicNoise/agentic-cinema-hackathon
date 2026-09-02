"""
Substitution loop tests.

The loop is the product's differentiator, so its behaviour is pinned here with
fakes rather than live services: a proposal that has not itself been cleared
must never be presented as a fix, and the agent must keep trying until one is.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clearcut.agents.substitute import SubstitutionAgent, _Candidate
from clearcut.core.models import (
    Adjudication,
    ClearableItem,
    ClearanceCategory,
    ResearchEvidence,
    RiskLevel,
    ScriptLocation,
    Verdict,
)


def _item(value: str, category=ClearanceCategory.BUSINESS_NAME) -> ClearableItem:
    return ClearableItem(
        id="itm_test",
        category=category,
        value=value,
        locations=[ScriptLocation(page=3, scene_number="4", quote=f"{value} sign")],
        context="depicted running a fraud",
        is_depicted_negatively=True,
    )


def _ruling(verdict=Verdict.MUST_CHANGE) -> Adjudication:
    return Adjudication(
        item_id="itm_test",
        verdict=verdict,
        risk=RiskLevel.HIGH,
        rationale="Live registered mark depicted committing fraud.",
        rule_applied="TRADEMARK_TARNISHMENT",
    )


class _FakeSearch:
    """Stands in for Parallel; returns empty evidence cheaply."""

    def __init__(self):
        self.calls = 0

    def search(self, *, item_id, objective, queries, mode="fast", **kw):
        self.calls += 1
        return ResearchEvidence(item_id=item_id, objective=objective, queries=queries)


class _FakeAdjudicator:
    """Returns a scripted verdict per candidate value."""

    def __init__(self, verdicts: dict[str, Verdict]):
        self._verdicts = verdicts
        self.calls = 0

    def run(self, decisions, evidence):
        self.calls += 1
        out = {}
        for d in decisions:
            v = self._verdicts.get(d.item.value, Verdict.CLEAR)
            out[d.item.id] = Adjudication(
                item_id=d.item.id, verdict=v, risk=RiskLevel.LOW, rationale="fake"
            )
        return out


def _agent(monkeypatch, candidates, verdicts):
    search = _FakeSearch()
    adj = _FakeAdjudicator(verdicts)
    agent = SubstitutionAgent(research=search, adjudicator=adj)
    monkeypatch.setattr(
        agent, "_propose", lambda item, ruling: [_Candidate(value=c, reason="r") for c in candidates]
    )
    return agent, search, adj


def test_accepts_first_clear_candidate(monkeypatch):
    agent, search, adj = _agent(
        monkeypatch, ["Halloran Auto"], {"Halloran Auto": Verdict.CLEAR}
    )
    subs = agent.run([_item("Zenith Motors")], {"itm_test": _ruling()})

    s = subs["itm_test"]
    assert s.verified_clear is True
    assert s.proposed == "Halloran Auto"
    assert s.attempts == 1
    assert s.rejected_candidates == []


def test_retries_until_a_candidate_verifies(monkeypatch):
    """A rejected candidate must not be presented as the fix."""
    agent, search, adj = _agent(
        monkeypatch,
        ["Delaney Motors", "Ostrander Motors", "Kilbray Motors"],
        {
            "Delaney Motors": Verdict.MUST_CHANGE,
            "Ostrander Motors": Verdict.MUST_CHANGE,
            "Kilbray Motors": Verdict.CLEAR,
        },
    )
    subs = agent.run([_item("Zenith Motors")], {"itm_test": _ruling()})

    s = subs["itm_test"]
    assert s.verified_clear is True
    assert s.proposed == "Kilbray Motors"
    assert s.attempts == 3
    assert s.rejected_candidates == ["Delaney Motors", "Ostrander Motors"]


def test_reports_failure_when_no_candidate_clears(monkeypatch):
    """Never present an unverified proposal as clean."""
    agent, _, _ = _agent(
        monkeypatch,
        ["A Motors", "B Motors", "C Motors"],
        {c: Verdict.MUST_CHANGE for c in ["A Motors", "B Motors", "C Motors"]},
    )
    subs = agent.run([_item("Zenith Motors")], {"itm_test": _ruling()})

    s = subs["itm_test"]
    assert s.verified_clear is False
    assert len(s.rejected_candidates) == 3


def test_clear_with_caution_is_acceptable(monkeypatch):
    agent, _, _ = _agent(
        monkeypatch, ["Marbury Auto"], {"Marbury Auto": Verdict.CLEAR_WITH_CAUTION}
    )
    subs = agent.run([_item("Zenith Motors")], {"itm_test": _ruling()})
    assert subs["itm_test"].verified_clear is True


def test_only_targets_must_change_items(monkeypatch):
    """Items that cleared, or need a licence, are not substitutable."""
    agent, _, _ = _agent(monkeypatch, ["x"], {})
    for verdict in (Verdict.CLEAR, Verdict.CLEAR_WITH_CAUTION, Verdict.LICENSE_REQUIRED):
        assert agent.run([_item("Zenith Motors")], {"itm_test": _ruling(verdict)}) == {}


def test_phone_substitution_settles_by_rule_without_research(monkeypatch):
    """A 555-block replacement is provably clear — it must not cost a lookup."""
    agent, search, adj = _agent(
        monkeypatch, ["555-0147"], {}
    )
    subs = agent.run(
        [_item("312-664-9920", ClearanceCategory.PHONE_NUMBER)],
        {"itm_test": _ruling()},
    )
    s = subs["itm_test"]
    assert s.verified_clear is True
    assert s.proposed == "555-0147"
    assert search.calls == 0, "rule-settled candidate should not hit Parallel"
    assert adj.calls == 0, "rule-settled candidate should not hit Gemini"
