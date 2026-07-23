"""Tests for the shared extensions report primitives."""

from __future__ import annotations

from urdf_live_editor.extensions.report import Issue, Report, Severity


def _report(*issues: Issue) -> Report:
    return Report(name="demo", issues=list(issues))


def test_severity_ordering():
    assert Severity.INFO < Severity.WARNING < Severity.ERROR
    assert max(Severity.INFO, Severity.ERROR, Severity.WARNING) is Severity.ERROR
    assert Severity.WARNING.label == "WARNING"


def test_empty_report_is_ok_and_clean():
    report = _report()
    assert report.ok
    assert report.clean
    assert report.worst() is Severity.INFO
    assert report.summary() == "demo: ok"


def test_ok_true_with_only_warnings():
    report = _report(Issue(Severity.WARNING, "w", "a warning"))
    assert report.ok            # warnings do not fail
    assert not report.clean     # but it is not clean
    assert report.worst() is Severity.WARNING


def test_ok_false_with_error():
    report = _report(
        Issue(Severity.WARNING, "w", "warn"),
        Issue(Severity.ERROR, "e", "boom", subject="link_1"),
    )
    assert not report.ok
    assert report.worst() is Severity.ERROR
    assert [i.subject for i in report.errors()] == ["link_1"]
    assert len(report.warnings()) == 1


def test_of_code_filters():
    report = _report(
        Issue(Severity.ERROR, "dup", "x"),
        Issue(Severity.ERROR, "dup", "y"),
        Issue(Severity.INFO, "other", "z"),
    )
    assert len(report.of_code("dup")) == 2
    assert len(report.of_code("other")) == 1


def test_to_dict_is_json_ready():
    report = _report(Issue(Severity.ERROR, "e", "boom", subject="j1"))
    data = report.to_dict()
    assert data["name"] == "demo"
    assert data["ok"] is False
    assert data["worst_label"] == "ERROR"
    assert data["issues"][0] == {
        "severity": 2,
        "severity_label": "ERROR",
        "code": "e",
        "message": "boom",
        "subject": "j1",
    }
