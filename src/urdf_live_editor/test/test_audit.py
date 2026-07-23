"""Tests for the append-only, hash-chained audit trail."""

from __future__ import annotations

import json

import pytest

from urdf_live_editor.observability.audit import (
    GENESIS_HASH,
    AuditEntry,
    AuditTrail,
    diff_edit_summary,
)


class Clock:
    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def tick(self, dt=1.0):
        self.t += dt
        return self.t


def test_record_populates_seq_and_hash_chain():
    trail = AuditTrail(clock=Clock())
    e0 = trail.record(actor="human:alice", action="apply", summary="add elbow")
    e1 = trail.record(actor="agent:editor", action="apply", summary="add wrist")
    assert e0.seq == 0 and e1.seq == 1
    assert e0.prev_hash == GENESIS_HASH
    assert e1.prev_hash == e0.entry_hash
    assert e0.entry_hash and e1.entry_hash
    assert e0.entry_hash != e1.entry_hash


def test_head_and_len():
    trail = AuditTrail(clock=Clock())
    assert len(trail) == 0
    assert trail.head is None
    trail.record(actor="a", action="apply")
    assert len(trail) == 1
    assert trail.head.action == "apply"


def test_verify_detects_intact_chain():
    trail = AuditTrail(clock=Clock())
    for i in range(5):
        trail.record(actor="a", action="apply", summary=f"e{i}")
    assert trail.is_intact()
    assert trail.verify() == []


def test_verify_detects_tampering():
    trail = AuditTrail(clock=Clock())
    trail.record(actor="a", action="apply", summary="original")
    trail.record(actor="a", action="apply", summary="second")
    # Tamper with the stored entry in place.
    tampered = AuditEntry.from_dict({**trail.entries()[0].to_dict(), "summary": "hacked"})
    trail._entries[0] = tampered  # noqa: SLF001 - deliberate corruption for the test
    problems = trail.verify()
    assert problems
    assert any("entry_hash mismatch" in p for p in problems)


def test_query_by_actor_and_action():
    trail = AuditTrail(clock=Clock())
    trail.record(actor="human:alice", action="apply", summary="a")
    trail.record(actor="agent:editor", action="rollback", summary="b")
    trail.record(actor="human:alice", action="rollback", summary="c")
    assert [e.summary for e in trail.query(actor="human:alice")] == ["c", "a"]
    assert [e.summary for e in trail.query(action="rollback")] == ["c", "b"]
    assert [e.summary for e in trail.query(actor="human:alice", action="rollback")] == ["c"]


def test_query_time_window_and_version():
    clock = Clock(start=100.0)
    trail = AuditTrail(clock=clock)
    trail.record(actor="a", action="apply", to_version="v1")
    clock.tick(10)
    trail.record(actor="a", action="apply", from_version="v1", to_version="v2")
    clock.tick(10)
    trail.record(actor="a", action="apply", from_version="v2", to_version="v3")
    # time window [105, 115] -> only the middle entry (ts=110)
    windowed = trail.query(since=105, until=115)
    assert [e.to_version for e in windowed] == ["v2"]
    # version matches either from_version or to_version
    assert {e.to_version for e in trail.query(version="v2")} == {"v2", "v3"}


def test_query_text_and_limit_and_order():
    trail = AuditTrail(clock=Clock())
    trail.record(actor="a", action="apply", summary="add elbow joint")
    trail.record(actor="a", action="apply", summary="add wrist joint")
    trail.record(actor="a", action="apply", summary="remove gripper")
    assert len(trail.query(text="joint")) == 2
    assert [e.summary for e in trail.query(limit=1)] == ["remove gripper"]
    oldest_first = trail.query(newest_first=False)
    assert oldest_first[0].summary == "add elbow joint"


def test_persistence_round_trip(tmp_path):
    path = str(tmp_path / "audit.jsonl")
    trail = AuditTrail(path=path, clock=Clock())
    trail.record(actor="human:alice", action="apply", summary="add elbow",
                 operation={"operation": "add_joint", "target": {"name": "elbow"}})
    trail.record(actor="agent:editor", action="rollback", summary="undo")

    # Re-open from disk.
    reloaded = AuditTrail(path=path)
    assert len(reloaded) == 2
    assert reloaded.is_intact()
    assert reloaded.entries()[0].summary == "add elbow"
    assert reloaded.entries()[0].operation["target"]["name"] == "elbow"

    # File is valid JSONL.
    with open(path, encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    assert len(lines) == 2
    assert lines[1]["prev_hash"] == lines[0]["entry_hash"]


def test_to_list_is_oldest_first():
    trail = AuditTrail(clock=Clock())
    trail.record(actor="a", action="apply", summary="first")
    trail.record(actor="a", action="apply", summary="second")
    listed = trail.to_list()
    assert [row["summary"] for row in listed] == ["first", "second"]


@pytest.mark.parametrize(
    "ops,expected",
    [
        ([], "no-op"),
        ([{"operation": "add_joint", "target": {"name": "elbow"}}], "add_joint elbow"),
        (
            [
                {"operation": "add_joint", "target": {"name": "elbow"}},
                {"operation": "rename", "target": {"name": "wrist"}},
            ],
            "add_joint elbow (+1 more)",
        ),
    ],
)
def test_diff_edit_summary(ops, expected):
    assert diff_edit_summary(ops) == expected
