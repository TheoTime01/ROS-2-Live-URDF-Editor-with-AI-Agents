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
Live Claude Agent SDK wiring for the URDF tools, hooks, and subagents.

This module is the *only* place that imports ``claude_agent_sdk``, and it does so
lazily inside functions so the rest of the package -- and the whole
recorded-response test suite -- imports and runs with no SDK and no API key.
When the SDK is installed, :func:`build_agent_options` assembles an in-process
MCP server exposing the six tools, registers the pre-tool mutation guard and the
post-tool audit hook, and declares the four subagents, all backed by the same
:class:`~urdf_ai_agents.tools.toolbox.UrdfToolbox`,
:class:`~urdf_ai_agents.hooks.MutationGuard`, and
:class:`~urdf_ai_agents.hooks.AuditTrail` the offline dispatcher uses.

The live entry point :func:`run_live` is exercised only by the opt-in live suite;
CI never reaches it.
"""

from urdf_ai_agents.agents.definitions import sdk_agents
from urdf_ai_agents.hooks import AuditTrail, MutationGuard
from urdf_ai_agents.tools.schemas import (
    allowed_tool_names, qualified_name, SERVER_NAME, SPEC_BY_NAME, TOOL_SPECS)
from urdf_ai_agents.tools.toolbox import ToolError


def sdk_available():
    """Return ``True`` when the ``claude_agent_sdk`` package can be imported."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def _require_sdk():
    """Import and return the SDK, raising a clear error when it is absent."""
    try:
        import claude_agent_sdk
    except ImportError as exc:
        raise RuntimeError(
            'the claude_agent_sdk package is required for live mode; install '
            'it, or use the recorded-response runtime for offline/CI use') \
            from exc
    return claude_agent_sdk


def build_mcp_server(toolbox):
    """Build an in-process SDK MCP server exposing the six URDF tools."""
    sdk = _require_sdk()
    tools = [_make_tool(sdk, spec, toolbox) for spec in TOOL_SPECS]
    return sdk.create_sdk_mcp_server(
        name=SERVER_NAME, version='1.0.0', tools=tools)


def _make_tool(sdk, spec, toolbox):
    """Wrap one :class:`ToolSpec` as an SDK ``@tool`` bound to ``toolbox``."""
    import json

    async def _handler(args):
        status, body = _run_tool(toolbox, spec.name, args)
        return {
            'content': [{'type': 'text', 'text': json.dumps(body)}],
            'isError': status >= 400,
        }

    return sdk.tool(spec.name, spec.description, spec.input_schema)(_handler)


def _run_tool(toolbox, name, args):
    """Invoke a toolbox method by tool name, returning ``(status, body)``."""
    try:
        if name == 'read_urdf':
            return toolbox.read_urdf()
        if name == 'describe_joint':
            return toolbox.describe_joint(args.get('name'))
        if name == 'validate_model':
            return toolbox.validate_model(
                urdf=args.get('urdf'), operations=args.get('operations'))
        if name == 'stage_edit':
            return toolbox.stage_edit(args.get('operations'))
        if name == 'apply_model':
            return toolbox.apply_model(
                args.get('operations'), label=args.get('label'))
        if name == 'rollback':
            return toolbox.rollback(args.get('target_index'))
    except ToolError as exc:
        return 400, {'error': exc.message, 'code': exc.code}
    return 400, {'error': "unknown tool '%s'" % name, 'code': 'UNKNOWN_TOOL'}


def build_hooks(toolbox, guard=None, audit=None):
    """Return SDK ``HookMatcher`` objects for the guard and the audit trail."""
    sdk = _require_sdk()
    guard = guard if guard is not None else MutationGuard()
    audit = audit if audit is not None else AuditTrail()

    async def _pre_tool(tool_name, input_data, context):
        spec = _spec_for(tool_name)
        if spec is None:
            return {'behavior': 'allow'}
        decision = guard.check(spec, input_data or {}, toolbox)
        if decision.allowed:
            return {'behavior': 'allow'}
        audit.record_blocked(spec.name, input_data or {}, decision.reason)
        return {'behavior': 'block', 'message': decision.reason}

    async def _post_tool(tool_name, input_data, output, context):
        spec = _spec_for(tool_name)
        if spec is not None:
            status, body = _parse_tool_output(output)
            audit.record(spec.name, input_data or {}, status, body)
        return {'behavior': 'continue'}

    matcher = 'mcp__%s__.*' % SERVER_NAME
    return {
        'PreToolUse': [sdk.HookMatcher(matcher=matcher, hooks=[_pre_tool])],
        'PostToolUse': [sdk.HookMatcher(matcher=matcher, hooks=[_post_tool])],
    }, audit


def _spec_for(qualified):
    """Return the :class:`ToolSpec` for a qualified tool name, or ``None``."""
    prefix = 'mcp__%s__' % SERVER_NAME
    if not qualified.startswith(prefix):
        return None
    return SPEC_BY_NAME.get(qualified[len(prefix):])


def _parse_tool_output(output):
    """Extract ``(status, body)`` from an SDK tool result, best-effort."""
    import json
    try:
        text = output['content'][0]['text']
        body = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        return 200, {}
    status = 400 if output.get('isError') else 200
    return status, body


def build_agent_options(toolbox, guard=None, audit=None, extra_options=None):
    """
    Assemble ``ClaudeAgentOptions`` wiring tools, hooks, and subagents.

    Returns ``(options, audit)`` so the caller can read the audit trail after a
    live run. ``extra_options`` overrides individual option fields.
    """
    sdk = _require_sdk()
    server = build_mcp_server(toolbox)
    hooks, audit = build_hooks(toolbox, guard=guard, audit=audit)
    agents = {
        slug: sdk.AgentDefinition(**kwargs)
        for slug, kwargs in sdk_agents().items()}
    fields = {
        'mcp_servers': {SERVER_NAME: server},
        'allowed_tools': allowed_tool_names(),
        'hooks': hooks,
        'agents': agents,
    }
    if extra_options:
        fields.update(extra_options)
    return sdk.ClaudeAgentOptions(**fields), audit


async def run_live(instruction, toolbox, agent='urdf-editor', extra_options=None):
    """
    Run one instruction against live Claude via the SDK (opt-in only).

    Returns ``(messages, audit)``. Requires ``claude_agent_sdk`` and a
    configured API key; never invoked by the deterministic CI suite.
    """
    sdk = _require_sdk()
    options, audit = build_agent_options(
        toolbox, extra_options=extra_options)
    prompt = '@%s %s' % (agent, instruction) if agent else instruction
    messages = []
    async for message in sdk.query(prompt=prompt, options=options):
        messages.append(message)
    return messages, audit


# Re-exported for callers that want the qualified name without importing schemas.
qualified = qualified_name
