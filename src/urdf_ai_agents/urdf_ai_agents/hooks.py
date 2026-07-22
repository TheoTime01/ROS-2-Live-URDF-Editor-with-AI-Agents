# Copyright 2026 theotime01
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Pre- and post-tool hooks that fence and audit the mutating tools.

The Claude Agent SDK lets a caller intercept every tool invocation. This module
holds the deterministic logic those hooks run, kept free of the SDK so the
dispatcher and tests can exercise it directly:

* :class:`MutationGuard` (pre-tool) enforces that a commit only ever lands a
  candidate that was *staged and validated first* -- the AI cannot skip straight
  to ``apply_model``. This is a second belt on top of the coordinator's own
  refusal to commit an invalid candidate.
* :class:`AuditTrail` (post-tool) records an ordered, JSON-serializable log of
  every tool call, capturing the version diff of each applied edit so every
  change the AI makes is reconstructable.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from urdf_ai_agents.tools.toolbox import operations_key


@dataclass(frozen=True)
class GuardDecision:
    """A pre-tool verdict: allow the call, or block it with a reason."""

    allowed: bool
    reason: Optional[str] = None

    @classmethod
    def allow(cls):
        """Return an allowing decision."""
        return cls(True, None)

    @classmethod
    def block(cls, reason):
        """Return a blocking decision carrying ``reason``."""
        return cls(False, reason)


class MutationGuard:
    """Pre-tool guard: a commit must target a freshly staged valid candidate."""

    def check(self, spec, args, toolbox):
        """Return a :class:`GuardDecision` for calling ``spec`` with ``args``."""
        if not spec.mutating:
            return GuardDecision.allow()
        # rollback restores an already-committed (already-validated) version, so
        # it needs no staged candidate; only apply_model introduces new state.
        if spec.name == 'rollback':
            return GuardDecision.allow()
        staged = toolbox.last_staged
        if staged is None:
            return GuardDecision.block(
                'apply_model must be preceded by stage_edit; no candidate has '
                'been staged')
        if not staged['is_valid']:
            return GuardDecision.block(
                'the last staged candidate failed validation; fix the '
                'operations and stage again before applying')
        if staged['key'] != operations_key(args.get('operations')):
            return GuardDecision.block(
                'apply_model operations do not match the staged candidate; '
                'stage exactly the operations you intend to apply')
        return GuardDecision.allow()


@dataclass
class AuditEntry:
    """One line of the audit log for a single tool call."""

    seq: int
    tool: str
    args: dict
    status: Optional[int] = None
    blocked: bool = False
    reason: Optional[str] = None
    version: Optional[int] = None
    diff: Optional[dict] = None

    def to_dict(self):
        """Return a JSON-serializable view of this entry."""
        return {
            'seq': self.seq,
            'tool': self.tool,
            'args': self.args,
            'status': self.status,
            'blocked': self.blocked,
            'reason': self.reason,
            'version': self.version,
            'diff': self.diff,
        }


@dataclass
class AuditTrail:
    """Post-tool sink: an ordered log of every tool call and applied diff."""

    entries: List[AuditEntry] = field(default_factory=list)

    def record_blocked(self, tool, args, reason):
        """Append an entry for a call the guard refused."""
        return self._append(AuditEntry(
            self._next_seq(), tool, args, blocked=True, reason=reason))

    def record(self, tool, args, status, body):
        """Append an entry for a completed call, capturing an apply diff."""
        version = None
        diff = None
        if isinstance(body, dict):
            if body.get('applied') and isinstance(body.get('version'), dict):
                version = body['version'].get('index')
                diff = body.get('diff')
            elif tool == 'rollback' and isinstance(body.get('version'), dict):
                version = body['version'].get('index')
        return self._append(AuditEntry(
            self._next_seq(), tool, args, status=status,
            version=version, diff=diff))

    def applied_entries(self):
        """Return the entries that committed a new version with a diff."""
        return [e for e in self.entries if e.diff is not None]

    def to_list(self):
        """Return the whole trail as a list of dicts."""
        return [entry.to_dict() for entry in self.entries]

    def _next_seq(self):
        """Return the sequence number for the next entry."""
        return len(self.entries)

    def _append(self, entry):
        """Append ``entry`` and return it."""
        self.entries.append(entry)
        return entry
