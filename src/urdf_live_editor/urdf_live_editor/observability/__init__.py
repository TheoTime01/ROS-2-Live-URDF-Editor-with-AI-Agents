"""Observability primitives for the URDF live editor (Milestone 5).

Three cooperating, ROS-independent building blocks:

* :mod:`~urdf_live_editor.observability.structured_logging` — JSONL structured
  logging with bound context.
* :mod:`~urdf_live_editor.observability.diagnostics` — subsystem health
  aggregation (OK/WARN/ERROR/STALE) for the status dashboard.
* :mod:`~urdf_live_editor.observability.audit` — an append-only, hash-chained
  audit trail of applied model changes, surfaced by the web audit viewer.

All three are deterministic and unit-tested without ROS or network access; the
ROS/web bridges are thin wrappers documented under ``docs/``.
"""

from __future__ import annotations

from .audit import GENESIS_HASH, AuditEntry, AuditTrail, diff_edit_summary
from .diagnostics import (
    ComponentStatus,
    Diagnostics,
    DiagnosticLevel,
    DiagnosticsReport,
)
from .structured_logging import (
    LogLevel,
    LogRecord,
    StructuredLogger,
    configure,
    get_logger,
)

__all__ = [
    # logging
    "LogLevel",
    "LogRecord",
    "StructuredLogger",
    "configure",
    "get_logger",
    # diagnostics
    "DiagnosticLevel",
    "ComponentStatus",
    "DiagnosticsReport",
    "Diagnostics",
    # audit
    "AuditEntry",
    "AuditTrail",
    "GENESIS_HASH",
    "diff_edit_summary",
]
