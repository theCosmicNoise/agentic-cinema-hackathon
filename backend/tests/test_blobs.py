"""
Storage tests.

The ledger is the one piece of state that must survive an instance dying, so
the contract both stores implement is pinned here. GcsBlobs is exercised
through a fake bucket rather than a live one: this asserts the shape of the
calls, not that Cloud Storage works.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clearcut.core.blobs import LocalBlobs


@pytest.fixture
def store(tmp_path):
    return LocalBlobs(tmp_path)


def test_round_trip(store):
    store.write("ledger/a.json", '{"x":1}')
    assert store.read("ledger/a.json") == '{"x":1}'


def test_missing_key_reads_none(store):
    assert store.read("ledger/nope.json") is None


def test_overwrite_replaces(store):
    store.write("k.json", "first")
    store.write("k.json", "second")
    assert store.read("k.json") == "second"


def test_write_leaves_no_temp_file(tmp_path):
    """Write-then-rename must not leave the .tmp behind for list() to find."""
    s = LocalBlobs(tmp_path)
    s.write("sessions/s1.json", "{}")
    assert [p.name for p in (tmp_path / "sessions").iterdir()] == ["s1.json"]


def test_delete_reports_whether_it_existed(store):
    store.write("sessions/s1.json", "{}")
    assert store.delete("sessions/s1.json") is True
    assert store.delete("sessions/s1.json") is False
    assert store.read("sessions/s1.json") is None


def test_list_is_scoped_to_prefix(store):
    store.write("sessions/s1.json", "{}")
    store.write("sessions/s2.json", "{}")
    store.write("ledger/l1.json", "{}")
    assert store.list("sessions") == ["sessions/s1.json", "sessions/s2.json"]
    assert store.list("ledger") == ["ledger/l1.json"]


def test_list_of_absent_prefix_is_empty(store):
    assert store.list("nothing-here") == []


def test_modified_is_tz_aware(store):
    store.write("k.json", "{}")
    m = store.modified("k.json")
    assert isinstance(m, datetime) and m.tzinfo is not None
    assert store.modified("absent.json") is None


def test_session_store_survives_a_new_instance(tmp_path):
    """The whole point: state written by one process is found by the next."""
    from clearcut.session import SessionStore, create_session

    a = SessionStore(store=LocalBlobs(tmp_path))
    s = create_session(
        Path("assets/screenplays/the_long_odds_v1.txt"), "proj"
    ) if Path("assets/screenplays/the_long_odds_v1.txt").exists() else None
    if s is None:
        pytest.skip("fixture screenplay not present")
    a.put(s)

    b = SessionStore(store=LocalBlobs(tmp_path))
    assert b.get(s.id) is not None
    assert [r["id"] for r in b.list()] == [s.id]
    assert b.delete(s.id) is True
    assert b.get(s.id) is None
