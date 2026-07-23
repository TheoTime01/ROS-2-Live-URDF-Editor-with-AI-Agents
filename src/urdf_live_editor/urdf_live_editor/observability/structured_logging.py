"""Structured, JSON-line logging for the URDF live editor.

Milestone 5 (UX & robustness) needs machine-readable logs so the web UI's
diagnostics/audit viewer, CI, and operators can all consume the same event
stream. This module is deliberately free of any ROS 2 dependency so it can be
unit-tested offline; a thin ROS bridge is described in ``docs/`` and can wrap
:class:`StructuredLogger` around ``rclpy``'s logger when running inside a node.

Design goals
------------
* **One event == one JSON object == one line** (JSONL), so logs can be
  ``tail``-ed, ``grep``-ed, and streamed to the browser without a parser.
* **Bound context.** A logger carries structured context (node name, session,
  model version) that is merged into every event, so callers don't repeat it.
* **Stable schema.** Every record has ``ts``, ``level``, ``event``, ``logger``
  and an optional ``fields`` map. Downstream consumers can rely on these keys.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, Mapping, Optional, TextIO

__all__ = [
    "LogLevel",
    "LogRecord",
    "StructuredLogger",
    "get_logger",
    "configure",
]


class LogLevel(IntEnum):
    """Severity levels, ordered so numeric comparison works as a threshold.

    Values mirror ROS 2 / Python logging semantics closely enough that a ROS
    bridge can map them 1:1 (DEBUG=10 ... FATAL=50).
    """

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    FATAL = 50

    @classmethod
    def parse(cls, value: "LogLevel | str | int") -> "LogLevel":
        """Coerce a name (case-insensitive), int, or level into a ``LogLevel``."""
        if isinstance(value, LogLevel):
            return value
        if isinstance(value, int):
            return cls(value)
        name = str(value).strip().upper()
        # Accept a couple of common aliases.
        aliases = {"WARN": "WARNING", "CRITICAL": "FATAL", "CRIT": "FATAL"}
        name = aliases.get(name, name)
        try:
            return cls[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValueError(f"unknown log level: {value!r}") from exc


@dataclass(frozen=True)
class LogRecord:
    """An immutable, serializable log event."""

    ts: float
    level: LogLevel
    logger: str
    event: str
    fields: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return the canonical, JSON-ready dict for this record."""
        out: Dict[str, Any] = {
            "ts": round(self.ts, 6),
            "level": self.level.name,
            "logger": self.logger,
            "event": self.event,
        }
        if self.fields:
            out["fields"] = _jsonable(dict(self.fields))
        return out

    def to_json(self) -> str:
        """Serialize the record to a single-line JSON string."""
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


# A sink receives fully-formed records. The default sink writes JSONL to a
# stream, but tests and the web layer register in-memory sinks.
Sink = Callable[[LogRecord], None]


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of arbitrary values into JSON-safe structures.

    We never want a logging call to raise because a field wasn't serializable,
    so unknown objects fall back to ``repr``.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _jsonable(to_dict())
        except Exception:  # pragma: no cover - defensive
            pass
    return repr(value)


class _StreamSink:
    """A sink that writes one JSON line per record to a text stream."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def __call__(self, record: LogRecord) -> None:
        line = record.to_json()
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()


class StructuredLogger:
    """A logger that emits :class:`LogRecord` objects to registered sinks.

    Loggers are cheap; call :meth:`bind` to derive a child that carries extra
    context. The ``clock`` and ``sinks`` are shared through the module-level
    registry so tests can install a deterministic clock and capture output.
    """

    def __init__(
        self,
        name: str,
        *,
        context: Optional[Mapping[str, Any]] = None,
        registry: "Optional[_Registry]" = None,
    ) -> None:
        self.name = name
        self._context: Dict[str, Any] = dict(context or {})
        self._registry = registry or _default_registry

    # -- context -----------------------------------------------------------
    def bind(self, **context: Any) -> "StructuredLogger":
        """Return a child logger with additional bound context fields."""
        merged = {**self._context, **context}
        return StructuredLogger(self.name, context=merged, registry=self._registry)

    @property
    def context(self) -> Mapping[str, Any]:
        return dict(self._context)

    # -- emission ----------------------------------------------------------
    def log(self, level: LogLevel, event: str, /, **fields: Any) -> Optional[LogRecord]:
        """Emit ``event`` at ``level`` merged with bound context.

        Returns the emitted :class:`LogRecord`, or ``None`` if the level was
        below the configured threshold (useful for tests and for callers that
        want to avoid building expensive follow-up work).
        """
        level = LogLevel.parse(level)
        if level < self._registry.threshold:
            return None
        merged_fields = {**self._context, **fields}
        record = LogRecord(
            ts=self._registry.clock(),
            level=level,
            logger=self.name,
            event=event,
            fields=merged_fields,
        )
        self._registry.emit(record)
        return record

    def debug(self, event: str, /, **fields: Any) -> Optional[LogRecord]:
        return self.log(LogLevel.DEBUG, event, **fields)

    def info(self, event: str, /, **fields: Any) -> Optional[LogRecord]:
        return self.log(LogLevel.INFO, event, **fields)

    def warning(self, event: str, /, **fields: Any) -> Optional[LogRecord]:
        return self.log(LogLevel.WARNING, event, **fields)

    def error(self, event: str, /, **fields: Any) -> Optional[LogRecord]:
        return self.log(LogLevel.ERROR, event, **fields)

    def fatal(self, event: str, /, **fields: Any) -> Optional[LogRecord]:
        return self.log(LogLevel.FATAL, event, **fields)


class _Registry:
    """Process-wide logging configuration shared by all loggers.

    Keeping this in one object (rather than module globals) makes it trivial to
    construct an isolated registry in tests without leaking state.
    """

    def __init__(self) -> None:
        self.threshold: LogLevel = LogLevel.INFO
        self.clock: Callable[[], float] = time.time
        self._sinks: list[Sink] = []
        self._lock = threading.Lock()

    def emit(self, record: LogRecord) -> None:
        with self._lock:
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink(record)
            except Exception:  # pragma: no cover - a broken sink must not crash callers
                pass

    def add_sink(self, sink: Sink) -> None:
        with self._lock:
            self._sinks.append(sink)

    def remove_sink(self, sink: Sink) -> None:
        with self._lock:
            if sink in self._sinks:
                self._sinks.remove(sink)

    def reset(self) -> None:
        with self._lock:
            self._sinks.clear()
        self.threshold = LogLevel.INFO
        self.clock = time.time


_default_registry = _Registry()
# Ship with a stderr JSONL sink so "just import and log" produces useful output.
_default_registry.add_sink(_StreamSink(sys.stderr))


def configure(
    *,
    level: "LogLevel | str | int | None" = None,
    clock: Optional[Callable[[], float]] = None,
    stream: Optional[TextIO] = None,
    add_sink: Optional[Sink] = None,
    reset_sinks: bool = False,
    registry: _Registry = _default_registry,
) -> None:
    """Configure the shared logging registry.

    Parameters
    ----------
    level:
        Minimum level to emit. Records below this are dropped.
    clock:
        A zero-arg callable returning a POSIX timestamp; injected in tests for
        deterministic output.
    stream:
        If given, replace all sinks with a single JSONL sink on this stream.
    add_sink:
        Register an additional sink (e.g. an in-memory buffer for the web UI).
    reset_sinks:
        Remove all existing sinks first.
    """
    if level is not None:
        registry.threshold = LogLevel.parse(level)
    if clock is not None:
        registry.clock = clock
    if reset_sinks or stream is not None:
        with registry._lock:  # noqa: SLF001 - internal coordination
            registry._sinks.clear()
    if stream is not None:
        registry.add_sink(_StreamSink(stream))
    if add_sink is not None:
        registry.add_sink(add_sink)


def get_logger(name: str, **context: Any) -> StructuredLogger:
    """Return a :class:`StructuredLogger` bound to ``name`` and ``context``."""
    return StructuredLogger(name, context=context or None)
