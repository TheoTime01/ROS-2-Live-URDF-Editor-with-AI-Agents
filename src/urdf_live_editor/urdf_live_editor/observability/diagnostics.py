"""Runtime diagnostics aggregation for the live editor stack.

This module collects the health of individual subsystems (URDF source watcher,
validation engine, joint-state adapter, web API, AI agents...) into a single
:class:`DiagnosticsReport` that the web UI renders as a status dashboard and
that a ROS bridge can translate into ``diagnostic_msgs/DiagnosticArray``.

It intentionally mirrors ROS 2's ``diagnostic_msgs`` status levels (OK / WARN /
ERROR / STALE) so the mapping to a real ROS diagnostics topic is trivial, but
carries no ROS dependency and is fully testable offline.

Typical use::

    diag = Diagnostics(clock=time.time)
    diag.report("validation", DiagnosticLevel.OK, "12 checks passed",
                 checks_passed=12)
    diag.heartbeat("urdf_source", stale_after=5.0)
    report = diag.snapshot()          # -> DiagnosticsReport
    payload = report.to_dict()        # -> JSON for the web dashboard
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Mapping, Optional

__all__ = [
    "DiagnosticLevel",
    "ComponentStatus",
    "DiagnosticsReport",
    "Diagnostics",
]


class DiagnosticLevel(IntEnum):
    """Health levels, ordered by increasing severity.

    Matches ``diagnostic_msgs/DiagnosticStatus`` byte values (OK=0, WARN=1,
    ERROR=2, STALE=3).
    """

    OK = 0
    WARN = 1
    ERROR = 2
    STALE = 3

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class ComponentStatus:
    """Health of a single named subsystem."""

    name: str
    level: DiagnosticLevel
    message: str = ""
    updated_at: float = 0.0
    values: Mapping[str, Any] = field(default_factory=dict)
    # When set, the component is considered STALE if no update arrives within
    # ``stale_after`` seconds of ``updated_at``.
    stale_after: Optional[float] = None

    def effective_level(self, now: float) -> DiagnosticLevel:
        """Return the level, upgrading to STALE if the heartbeat has expired."""
        if self.stale_after is not None and (now - self.updated_at) > self.stale_after:
            return DiagnosticLevel.STALE
        return self.level

    def to_dict(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        level = self.effective_level(now)
        return {
            "name": self.name,
            "level": level.value,
            "level_label": level.label,
            "message": self.message,
            "updated_at": round(self.updated_at, 6),
            "age": round(max(0.0, now - self.updated_at), 6),
            "stale_after": self.stale_after,
            "values": dict(self.values),
        }


@dataclass(frozen=True)
class DiagnosticsReport:
    """An immutable snapshot of overall system health."""

    generated_at: float
    components: List[ComponentStatus]

    @property
    def overall(self) -> DiagnosticLevel:
        """The worst (highest) level across all components; OK if empty."""
        if not self.components:
            return DiagnosticLevel.OK
        return max(c.effective_level(self.generated_at) for c in self.components)

    def healthy(self) -> bool:
        return self.overall == DiagnosticLevel.OK

    def problems(self) -> List[ComponentStatus]:
        """Components that are not OK, worst first."""
        now = self.generated_at
        bad = [c for c in self.components if c.effective_level(now) != DiagnosticLevel.OK]
        return sorted(bad, key=lambda c: c.effective_level(now), reverse=True)

    def to_dict(self) -> Dict[str, Any]:
        overall = self.overall
        return {
            "generated_at": round(self.generated_at, 6),
            "overall": overall.value,
            "overall_label": overall.label,
            "healthy": self.healthy(),
            "components": [c.to_dict(self.generated_at) for c in self.components],
        }


class Diagnostics:
    """A thread-safe registry of component statuses.

    Subsystems call :meth:`report` (or the convenience :meth:`ok` /
    :meth:`warn` / :meth:`error`) whenever their state changes, and
    :meth:`heartbeat` on a timer to prove liveness. :meth:`snapshot` produces an
    immutable :class:`DiagnosticsReport` for the dashboard.
    """

    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._components: Dict[str, ComponentStatus] = {}
        self._lock = threading.Lock()

    def report(
        self,
        name: str,
        level: DiagnosticLevel,
        message: str = "",
        *,
        stale_after: Optional[float] = None,
        **values: Any,
    ) -> ComponentStatus:
        """Set the status of component ``name``."""
        status = ComponentStatus(
            name=name,
            level=DiagnosticLevel(level),
            message=message,
            updated_at=self._clock(),
            values=dict(values),
            stale_after=stale_after,
        )
        with self._lock:
            self._components[name] = status
        return status

    def ok(self, name: str, message: str = "", **values: Any) -> ComponentStatus:
        return self.report(name, DiagnosticLevel.OK, message, **values)

    def warn(self, name: str, message: str = "", **values: Any) -> ComponentStatus:
        return self.report(name, DiagnosticLevel.WARN, message, **values)

    def error(self, name: str, message: str = "", **values: Any) -> ComponentStatus:
        return self.report(name, DiagnosticLevel.ERROR, message, **values)

    def heartbeat(
        self, name: str, *, stale_after: float, message: str = "alive"
    ) -> ComponentStatus:
        """Refresh a component's timestamp, marking it OK unless it later goes
        stale. Preserves any richer values from the previous report."""
        with self._lock:
            prev = self._components.get(name)
            values = dict(prev.values) if prev else {}
        return self.report(name, DiagnosticLevel.OK, message, stale_after=stale_after, **values)

    def remove(self, name: str) -> None:
        with self._lock:
            self._components.pop(name, None)

    def get(self, name: str) -> Optional[ComponentStatus]:
        with self._lock:
            return self._components.get(name)

    def snapshot(self) -> DiagnosticsReport:
        with self._lock:
            components = list(self._components.values())
        # Stable, human-friendly ordering: worst-first, then by name.
        now = self._clock()
        components.sort(key=lambda c: (-c.effective_level(now).value, c.name))
        return DiagnosticsReport(generated_at=now, components=components)
