"""Tests for the structured JSONL logging layer."""

from __future__ import annotations

import io
import json

import pytest

from urdf_live_editor.observability.structured_logging import (
    LogLevel,
    LogRecord,
    StructuredLogger,
    _Registry,
)


@pytest.fixture()
def registry():
    """An isolated registry with a deterministic clock and a capturing sink."""
    reg = _Registry()
    reg.threshold = LogLevel.DEBUG
    reg.clock = lambda: 1000.0
    captured: list[LogRecord] = []
    reg.add_sink(captured.append)
    return reg, captured


def make_logger(registry, name="test", **ctx):
    reg, _ = registry
    return StructuredLogger(name, context=ctx or None, registry=reg)


def test_emits_record_with_stable_schema(registry):
    log = make_logger(registry)
    record = log.info("model_applied", version="v3", joints=5)
    assert record is not None
    data = record.to_dict()
    assert data["ts"] == 1000.0
    assert data["level"] == "INFO"
    assert data["logger"] == "test"
    assert data["event"] == "model_applied"
    assert data["fields"] == {"version": "v3", "joints": 5}


def test_bound_context_is_merged(registry):
    _, captured = registry
    log = make_logger(registry, node="web_api", session="s1")
    log.warning("slow_request", ms=1200)
    assert len(captured) == 1
    fields = captured[0].fields
    assert fields["node"] == "web_api"
    assert fields["session"] == "s1"
    assert fields["ms"] == 1200


def test_bind_creates_child_without_mutating_parent(registry):
    parent = make_logger(registry, node="a")
    child = parent.bind(request="r1")
    assert "request" not in parent.context
    assert child.context["request"] == "r1"
    assert child.context["node"] == "a"


def test_threshold_drops_lower_levels(registry):
    reg, captured = registry
    reg.threshold = LogLevel.WARNING
    log = make_logger(registry)
    assert log.info("ignored") is None
    assert log.error("kept") is not None
    assert [r.event for r in captured] == ["kept"]


def test_json_is_single_line_and_sorted():
    record = LogRecord(
        ts=1.5, level=LogLevel.ERROR, logger="x", event="boom",
        fields={"b": 2, "a": 1},
    )
    line = record.to_json()
    assert "\n" not in line
    parsed = json.loads(line)
    assert parsed["fields"] == {"a": 1, "b": 2}
    # keys sorted -> "a" appears before "b" in the raw text
    assert line.index('"a"') < line.index('"b"')


def test_non_serializable_fields_fall_back_to_repr(registry):
    class Weird:
        def __repr__(self):
            return "<weird>"

    log = make_logger(registry)
    record = log.info("odd", obj=Weird())
    assert record.to_dict()["fields"]["obj"] == "<weird>"


def test_object_with_to_dict_is_expanded(registry):
    class Thing:
        def to_dict(self):
            return {"kind": "thing", "n": 3}

    log = make_logger(registry)
    record = log.info("has_obj", thing=Thing())
    assert record.to_dict()["fields"]["thing"] == {"kind": "thing", "n": 3}


def test_stream_sink_writes_jsonl():
    reg = _Registry()
    reg.clock = lambda: 42.0
    stream = io.StringIO()
    from urdf_live_editor.observability.structured_logging import _StreamSink

    reg.add_sink(_StreamSink(stream))
    log = StructuredLogger("s", registry=reg)
    log.info("one")
    log.info("two")
    lines = stream.getvalue().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "one"
    assert json.loads(lines[1])["event"] == "two"


def test_broken_sink_does_not_crash_caller(registry):
    reg, captured = registry

    def boom(_record):
        raise RuntimeError("sink failed")

    reg.add_sink(boom)
    log = StructuredLogger("s", registry=reg)
    # Should not raise even though one sink throws.
    log.info("still_works")
    assert captured[-1].event == "still_works"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("warn", LogLevel.WARNING),
        ("CRITICAL", LogLevel.FATAL),
        (40, LogLevel.ERROR),
        (LogLevel.DEBUG, LogLevel.DEBUG),
    ],
)
def test_level_parse(value, expected):
    assert LogLevel.parse(value) == expected


def test_level_parse_rejects_unknown():
    with pytest.raises(ValueError):
        LogLevel.parse("banana")
