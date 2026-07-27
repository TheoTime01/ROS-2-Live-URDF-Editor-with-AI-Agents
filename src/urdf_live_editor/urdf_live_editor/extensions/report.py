"""Shared, JSON-ready validation/report primitives for the extensions layer.

Milestone 6 adds several deterministic *extension* capabilities on top of the
trusted core — ``ros2_control`` generation, Gazebo simulation artifacts,
multi-model sessions, and collision/inertial validation. Each of them needs a
way to accumulate findings at different severities and hand a stable,
serializable result back to the web UI, an agent, or a test.

Rather than every module reinventing that shape (as the earlier milestones each
did for their own concerns), the extensions share these small primitives:

* :class:`Severity` — ``INFO`` < ``WARNING`` < ``ERROR``.
* :class:`Issue` — one finding, with a stable machine ``code`` and a subject.
* :class:`Report` — an ordered collection of issues with convenience queries
  (:pyattr:`Report.ok`, :meth:`Report.errors`, :meth:`Report.worst`, ...).

Everything here is pure Python: no ROS, no LLM, no I/O. That keeps the whole
extensions layer unit-testable offline, in line with the project's
"deterministic core first" principle — the AI layer can explain these reports
but never fabricate a passing one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional

__all__ = [
    "Severity",
    "Issue",
    "Report",
]


class Severity(IntEnum):
    """Finding severity, ordered so ``max()`` yields the worst level."""

    INFO = 0
    WARNING = 1
    ERROR = 2

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class Issue:
    """A single finding produced by an extension validator/generator.

    Parameters
    ----------
    severity:
        How serious the finding is.
    code:
        A short, stable machine-readable identifier (e.g. ``"mass_nonpositive"``)
        so callers and tests can match on it without parsing prose.
    message:
        A human-readable explanation.
    subject:
        The model element the finding is about — a link, joint, or session name.
        ``None`` for whole-model findings.
    """

    severity: Severity
    code: str
    message: str
    subject: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "severity_label": self.severity.label,
            "code": self.code,
            "message": self.message,
            "subject": self.subject,
        }


@dataclass(frozen=True)
class Report:
    """An ordered set of :class:`Issue` findings for one named check."""

    name: str
    issues: List[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when there are no ``ERROR``-level issues (warnings are allowed)."""
        return not any(i.severity is Severity.ERROR for i in self.issues)

    @property
    def clean(self) -> bool:
        """True when there are no issues at all (not even info/warnings)."""
        return not self.issues

    def of_severity(self, severity: Severity) -> List[Issue]:
        return [i for i in self.issues if i.severity is severity]

    def errors(self) -> List[Issue]:
        return self.of_severity(Severity.ERROR)

    def warnings(self) -> List[Issue]:
        return self.of_severity(Severity.WARNING)

    def of_code(self, code: str) -> List[Issue]:
        return [i for i in self.issues if i.code == code]

    def worst(self) -> Severity:
        """The highest severity present, or ``INFO`` when empty."""
        if not self.issues:
            return Severity.INFO
        return max(i.severity for i in self.issues)

    def summary(self) -> str:
        if self.clean:
            return f"{self.name}: ok"
        counts = {sev.label: len(self.of_severity(sev)) for sev in Severity}
        parts = [f"{n} {label.lower()}" for label, n in counts.items() if n]
        return f"{self.name}: {', '.join(parts)}"

    def to_dict(self) -> Dict[str, Any]:
        worst = self.worst()
        return {
            "name": self.name,
            "ok": self.ok,
            "clean": self.clean,
            "worst": worst.value,
            "worst_label": worst.label,
            "summary": self.summary(),
            "issues": [i.to_dict() for i in self.issues],
        }


class _Builder:
    """Internal helper letting validators accumulate issues ergonomically.

    Not exported; the public modules expose their own top-level functions that
    return a finished :class:`Report`.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._issues: List[Issue] = []

    def add(
        self,
        severity: Severity,
        code: str,
        message: str,
        subject: Optional[str] = None,
    ) -> None:
        self._issues.append(Issue(severity, code, message, subject))

    def info(self, code: str, message: str, subject: Optional[str] = None) -> None:
        self.add(Severity.INFO, code, message, subject)

    def warn(self, code: str, message: str, subject: Optional[str] = None) -> None:
        self.add(Severity.WARNING, code, message, subject)

    def error(self, code: str, message: str, subject: Optional[str] = None) -> None:
        self.add(Severity.ERROR, code, message, subject)

    def build(self) -> Report:
        return Report(name=self._name, issues=list(self._issues))
