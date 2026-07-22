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
The tool-call runtime that binds tools, guard, and audit together.

:class:`ToolDispatcher` is what actually runs a tool call: it looks up the
:class:`~urdf_ai_agents.tools.schemas.ToolSpec`, runs the
:class:`~urdf_ai_agents.hooks.MutationGuard` (the pre-tool hook), executes the
:class:`~urdf_ai_agents.tools.toolbox.UrdfToolbox` method, and records the call
in the :class:`~urdf_ai_agents.hooks.AuditTrail` (the post-tool hook). Every
path -- the recorded-response tests, the ROS node, and the live SDK MCP server
-- funnels through this one object, so the guard-and-audit discipline holds no
matter who is driving.
"""

from dataclasses import dataclass
from typing import Optional

from urdf_ai_agents.hooks import AuditTrail, MutationGuard
from urdf_ai_agents.tools.schemas import SPEC_BY_NAME
from urdf_ai_agents.tools.toolbox import ToolError


@dataclass
class ToolResult:
    """The outcome of one dispatched tool call."""

    tool: str
    ok: bool
    blocked: bool
    status: Optional[int]
    data: dict
    reason: Optional[str] = None

    def to_dict(self):
        """Return a JSON-serializable view of this result."""
        return {
            'tool': self.tool,
            'ok': self.ok,
            'blocked': self.blocked,
            'status': self.status,
            'data': self.data,
            'reason': self.reason,
        }


class ToolDispatcher:
    """Runs tool calls through the mutation guard and the audit trail."""

    def __init__(self, toolbox, guard=None, audit=None):
        """Wrap ``toolbox`` with an optional ``guard`` and ``audit`` sink."""
        self._toolbox = toolbox
        self._guard = guard if guard is not None else MutationGuard()
        self._audit = audit if audit is not None else AuditTrail()

    @property
    def toolbox(self):
        """Return the wrapped toolbox."""
        return self._toolbox

    @property
    def audit(self):
        """Return the audit trail."""
        return self._audit

    def call(self, tool, args=None):
        """Dispatch one call, always returning a :class:`ToolResult`."""
        args = dict(args or {})
        spec = SPEC_BY_NAME.get(tool)
        if spec is None:
            return ToolResult(
                tool, ok=False, blocked=False, status=400,
                data={'error': "unknown tool '%s'" % tool,
                      'code': 'UNKNOWN_TOOL'})

        decision = self._guard.check(spec, args, self._toolbox)
        if not decision.allowed:
            self._audit.record_blocked(tool, args, decision.reason)
            return ToolResult(
                tool, ok=False, blocked=True, status=None,
                data={'error': decision.reason, 'code': 'BLOCKED_BY_HOOK'},
                reason=decision.reason)

        try:
            status, body = self._invoke(tool, args)
        except ToolError as exc:
            body = {'error': exc.message, 'code': exc.code}
            self._audit.record(tool, args, 400, body)
            return ToolResult(
                tool, ok=False, blocked=False, status=400, data=body)

        self._audit.record(tool, args, status, body)
        return ToolResult(
            tool, ok=(status == 200), blocked=False, status=status, data=body)

    def _invoke(self, tool, args):
        """Route ``tool`` to its toolbox method, returning ``(status, body)``."""
        box = self._toolbox
        if tool == 'read_urdf':
            return box.read_urdf()
        if tool == 'describe_joint':
            return box.describe_joint(args.get('name'))
        if tool == 'validate_model':
            return box.validate_model(
                urdf=args.get('urdf'), operations=args.get('operations'))
        if tool == 'stage_edit':
            return box.stage_edit(args.get('operations'))
        if tool == 'apply_model':
            return box.apply_model(
                args.get('operations'), label=args.get('label'))
        if tool == 'rollback':
            return box.rollback(args.get('target_index'))
        raise ToolError('UNKNOWN_TOOL', "unknown tool '%s'" % tool)
