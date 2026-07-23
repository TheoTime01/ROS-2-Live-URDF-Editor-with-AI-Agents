"""Tests for the diagnostics aggregator."""

from __future__ import annotations

from urdf_live_editor.observability.diagnostics import (
    Diagnostics,
    DiagnosticLevel,
    DiagnosticsReport,
)


class Clock:
    def __init__(self, start=0.0):
        self.t = start

    def __call__(self):
        return self.t

    def set(self, t):
        self.t = t


def test_report_and_snapshot():
    diag = Diagnostics(clock=Clock(10.0))
    diag.ok("validation", "all good", checks=12)
    report = diag.snapshot()
    assert isinstance(report, DiagnosticsReport)
    assert report.healthy()
    assert report.overall == DiagnosticLevel.OK
    comp = report.components[0]
    assert comp.name == "validation"
    assert comp.values["checks"] == 12


def test_overall_is_worst_level():
    diag = Diagnostics(clock=Clock(1.0))
    diag.ok("a")
    diag.warn("b", "degraded")
    diag.error("c", "down")
    report = diag.snapshot()
    assert report.overall == DiagnosticLevel.ERROR
    assert not report.healthy()
    # problems() is worst-first
    assert [c.name for c in report.problems()] == ["c", "b"]


def test_snapshot_orders_worst_first_then_name():
    diag = Diagnostics(clock=Clock(1.0))
    diag.ok("zeta")
    diag.ok("alpha")
    diag.error("mike")
    names = [c.name for c in diag.snapshot().components]
    assert names[0] == "mike"  # error first
    assert names[1:] == ["alpha", "zeta"]  # then OK by name


def test_heartbeat_goes_stale():
    clock = Clock(0.0)
    diag = Diagnostics(clock=clock)
    diag.heartbeat("urdf_source", stale_after=5.0)
    # Fresh -> OK
    assert diag.snapshot().overall == DiagnosticLevel.OK
    # Advance past the stale window
    clock.set(6.0)
    report = diag.snapshot()
    assert report.overall == DiagnosticLevel.STALE
    assert report.components[0].effective_level(6.0) == DiagnosticLevel.STALE


def test_heartbeat_preserves_prior_values():
    clock = Clock(0.0)
    diag = Diagnostics(clock=clock)
    diag.ok("adapter", "running", rate_hz=30)
    diag.heartbeat("adapter", stale_after=5.0)
    comp = diag.get("adapter")
    assert comp.values["rate_hz"] == 30


def test_remove_component():
    diag = Diagnostics(clock=Clock(1.0))
    diag.ok("temp")
    assert diag.get("temp") is not None
    diag.remove("temp")
    assert diag.get("temp") is None
    assert diag.snapshot().components == []


def test_empty_report_is_healthy():
    report = Diagnostics(clock=Clock(1.0)).snapshot()
    assert report.healthy()
    assert report.overall == DiagnosticLevel.OK


def test_report_to_dict_shape():
    diag = Diagnostics(clock=Clock(100.0))
    diag.warn("web_api", "high latency", p99_ms=900)
    data = diag.snapshot().to_dict()
    assert data["overall_label"] == "WARN"
    assert data["healthy"] is False
    assert data["components"][0]["level_label"] == "WARN"
    assert data["components"][0]["values"]["p99_ms"] == 900
    assert "age" in data["components"][0]
