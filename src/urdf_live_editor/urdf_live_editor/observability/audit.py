"""Append-only audit trail for applied model changes.

The project's guiding principle #3 is *"Everything is auditable."* Every change
that reaches the active ``robot_description`` must leave a durable record of
**who** made it, **what** changed (the edit operation + resulting diff),
**when**, and the model **version** it produced. This module implements that
record as an append-only log with:

* an immutable :class:`AuditEntry` dataclass with a stable JSON schema,
* :class:`AuditTrail`, an in-memory + optionally file-backed (JSONL) log with
  filtering/query helpers used by the web audit-trail viewer,
* integrity chaining (each entry stores the hash of the previous one) so a
  truncated or tampered trail is detectable.

Like the rest of :mod:`observability`, this has no ROS dependency and is fully
unit-testable offline. The Milestone 4 post-tool hook is expected to call
:meth:`AuditTrail.record` after every applied edit.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

__all__ = [
    "AuditEntry",
    "AuditTrail",
    "GENESIS_HASH",
]

# The "previous hash" of the very first entry in a trail.
GENESIS_HASH = "0" * 64


def _canonical_json(obj: Any) -> str:
    """Deterministic JSON used both for storage and for hashing."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class AuditEntry:
    """One immutable audit record.

    Attributes
    ----------
    seq:
        Monotonic 0-based index within the trail.
    ts:
        POSIX timestamp of when the change was applied.
    actor:
        Who made the change, e.g. ``"human:alice"``, ``"agent:editor"``.
    action:
        The operation performed, e.g. ``"apply"``, ``"rollback"``,
        ``"add_joint"``.
    summary:
        Short human-readable description for list views.
    from_version / to_version:
        Model version ids before/after the change (``None`` where not
        applicable, e.g. the first load).
    operation:
        The structured ``EditOperation`` (or list of them) that was applied.
    diff:
        A structured or unified-text diff of the model change.
    metadata:
        Free-form extra context (session id, request id, agent reasoning...).
    prev_hash / entry_hash:
        Integrity chain. ``entry_hash`` covers all other fields plus
        ``prev_hash``.
    """

    seq: int
    ts: float
    actor: str
    action: str
    summary: str = ""
    from_version: Optional[str] = None
    to_version: Optional[str] = None
    operation: Any = None
    diff: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    prev_hash: str = GENESIS_HASH
    entry_hash: str = ""

    def _payload(self) -> Dict[str, Any]:
        """The fields that participate in the integrity hash (everything but
        the hash itself)."""
        return {
            "seq": self.seq,
            "ts": round(self.ts, 6),
            "actor": self.actor,
            "action": self.action,
            "summary": self.summary,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "operation": self.operation,
            "diff": self.diff,
            "metadata": dict(self.metadata),
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        """Return the SHA-256 hex digest of this entry's canonical payload."""
        return hashlib.sha256(_canonical_json(self._payload()).encode("utf-8")).hexdigest()

    def finalized(self) -> "AuditEntry":
        """Return a copy with ``entry_hash`` filled in from the payload."""
        return replace(self, entry_hash=self.compute_hash())

    def to_dict(self) -> Dict[str, Any]:
        data = self._payload()
        data["entry_hash"] = self.entry_hash
        return data

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuditEntry":
        return cls(
            seq=int(data["seq"]),
            ts=float(data["ts"]),
            actor=str(data["actor"]),
            action=str(data["action"]),
            summary=str(data.get("summary", "")),
            from_version=data.get("from_version"),
            to_version=data.get("to_version"),
            operation=data.get("operation"),
            diff=data.get("diff"),
            metadata=dict(data.get("metadata", {})),
            prev_hash=str(data.get("prev_hash", GENESIS_HASH)),
            entry_hash=str(data.get("entry_hash", "")),
        )


class AuditTrail:
    """An append-only, hash-chained audit log.

    Thread-safe. If ``path`` is given, entries are also appended to a JSONL file
    and loaded from it on construction, so the trail survives restarts.
    """

    def __init__(
        self,
        path: Optional[str] = None,
        *,
        clock=time.time,
    ) -> None:
        self._path = path
        self._clock = clock
        self._entries: List[AuditEntry] = []
        self._lock = threading.RLock()
        if path and os.path.exists(path):
            self._load(path)

    # -- construction / persistence ---------------------------------------
    def _load(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                self._entries.append(AuditEntry.from_dict(json.loads(line)))

    def _append_to_file(self, entry: AuditEntry) -> None:
        if not self._path:
            return
        directory = os.path.dirname(os.path.abspath(self._path))
        os.makedirs(directory, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(entry.to_json() + "\n")

    # -- writing ----------------------------------------------------------
    def record(
        self,
        *,
        actor: str,
        action: str,
        summary: str = "",
        from_version: Optional[str] = None,
        to_version: Optional[str] = None,
        operation: Any = None,
        diff: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
        ts: Optional[float] = None,
    ) -> AuditEntry:
        """Append a new entry and return it (with hashes populated)."""
        with self._lock:
            seq = len(self._entries)
            prev_hash = self._entries[-1].entry_hash if self._entries else GENESIS_HASH
            entry = AuditEntry(
                seq=seq,
                ts=self._clock() if ts is None else ts,
                actor=actor,
                action=action,
                summary=summary,
                from_version=from_version,
                to_version=to_version,
                operation=operation,
                diff=diff,
                metadata=dict(metadata or {}),
                prev_hash=prev_hash,
            ).finalized()
            self._entries.append(entry)
            self._append_to_file(entry)
            return entry

    # -- reading ----------------------------------------------------------
    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[AuditEntry]:
        return iter(list(self._entries))

    @property
    def head(self) -> Optional[AuditEntry]:
        """The most recent entry, or ``None`` for an empty trail."""
        with self._lock:
            return self._entries[-1] if self._entries else None

    def entries(self) -> List[AuditEntry]:
        with self._lock:
            return list(self._entries)

    def query(
        self,
        *,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        version: Optional[str] = None,
        text: Optional[str] = None,
        limit: Optional[int] = None,
        newest_first: bool = True,
    ) -> List[AuditEntry]:
        """Filter the trail. All conditions are ANDed together.

        Parameters mirror what the web audit-trail viewer exposes as filters:
        by actor, action, time window, model version (matches either
        ``from_version`` or ``to_version``), and a free-text search over
        ``summary``/``action``/``actor``.
        """
        needle = text.lower() if text else None
        results: List[AuditEntry] = []
        for entry in self._entries:
            if actor is not None and entry.actor != actor:
                continue
            if action is not None and entry.action != action:
                continue
            if since is not None and entry.ts < since:
                continue
            if until is not None and entry.ts > until:
                continue
            if version is not None and version not in (entry.from_version, entry.to_version):
                continue
            if needle is not None and needle not in (
                f"{entry.summary} {entry.action} {entry.actor}".lower()
            ):
                continue
            results.append(entry)
        if newest_first:
            results.reverse()
        if limit is not None:
            results = results[:limit]
        return results

    def to_list(self) -> List[Dict[str, Any]]:
        """JSON-ready list of all entries (oldest first) for API responses."""
        return [entry.to_dict() for entry in self._entries]

    # -- integrity --------------------------------------------------------
    def verify(self) -> List[str]:
        """Verify the hash chain and sequence numbering.

        Returns a list of human-readable problem descriptions; an empty list
        means the trail is intact.
        """
        problems: List[str] = []
        prev_hash = GENESIS_HASH
        with self._lock:
            for i, entry in enumerate(self._entries):
                if entry.seq != i:
                    problems.append(f"entry {i}: seq is {entry.seq}, expected {i}")
                if entry.prev_hash != prev_hash:
                    problems.append(
                        f"entry {i}: prev_hash {entry.prev_hash[:8]}… "
                        f"does not match previous entry hash {prev_hash[:8]}…"
                    )
                recomputed = entry.compute_hash()
                if entry.entry_hash != recomputed:
                    problems.append(
                        f"entry {i}: entry_hash mismatch (record was modified)"
                    )
                prev_hash = entry.entry_hash
        return problems

    def is_intact(self) -> bool:
        return not self.verify()


def diff_edit_summary(operations: Sequence[Mapping[str, Any]]) -> str:
    """Build a short human summary for a batch of ``EditOperation`` dicts.

    Small helper used by callers that record audit entries so the viewer's
    one-line summary is consistent.
    """
    if not operations:
        return "no-op"
    parts: List[str] = []
    for op in operations:
        name = ""
        target = op.get("target") if isinstance(op, Mapping) else None
        if isinstance(target, Mapping):
            name = str(target.get("name", ""))
        verb = str(op.get("operation", "edit")) if isinstance(op, Mapping) else "edit"
        parts.append(f"{verb} {name}".strip())
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} (+{len(parts) - 1} more)"
