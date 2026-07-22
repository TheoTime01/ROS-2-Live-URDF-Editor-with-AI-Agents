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
The agent session and its deterministic (recorded) planner.

An :class:`AgentSession` turns a natural-language instruction into a sequence of
tool calls run through the :class:`~urdf_ai_agents.dispatch.ToolDispatcher`. The
*planner* decides which tools to call; swapping the planner is what lets the very
same session code run either against live Claude (see
:mod:`urdf_ai_agents.sdk_adapter`) or against a :class:`RecordedPlanner` that
replays a fixed transcript. The recorded path is what makes the AI layer
reproducible in CI: the tool arguments (the EditOperation JSON an LLM would emit)
come from a fixture, but every stage/validate/apply/guard/audit step is the real
deterministic core.
"""

import abc
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class ToolCall:
    """A single planned tool invocation."""

    tool: str
    args: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        """Build a call from ``{'tool': ..., 'args': {...}}``."""
        return cls(data['tool'], dict(data.get('args', {})))


@dataclass
class SessionResult:
    """Everything one instruction produced: transcript, message, and audit."""

    instruction: str
    transcript: List[dict]
    final_message: str
    audit: List[dict]

    @property
    def applied(self):
        """Return ``True`` when at least one tool call committed a version."""
        return any(
            entry['tool'] == 'apply_model' and entry['ok']
            for entry in self.transcript)

    @property
    def blocked_calls(self):
        """Return the transcript entries the mutation guard refused."""
        return [entry for entry in self.transcript if entry['blocked']]


class Planner(abc.ABC):
    """Decides the tool calls (and closing message) for an instruction."""

    @abc.abstractmethod
    def plan(self, instruction):
        """Return ``(list_of_ToolCall, final_message)`` for ``instruction``."""


@dataclass
class RecordedScenario:
    """A scripted transcript: the tool calls and closing message to replay."""

    tool_calls: List[ToolCall]
    final_message: str = ''

    @classmethod
    def from_dict(cls, data):
        """Build a scenario from a plain dict (e.g. loaded from JSON)."""
        return cls(
            [ToolCall.from_dict(item) for item in data.get('tool_calls', [])],
            data.get('final_message', ''))


class RecordedPlanner(Planner):
    """A planner that replays recorded scenarios keyed by instruction."""

    def __init__(self, scenarios=None, default=None):
        """Map instructions to :class:`RecordedScenario` values."""
        self._scenarios = dict(scenarios or {})
        self._default = default

    @classmethod
    def from_dict(cls, data):
        """
        Build a planner from ``{instruction: scenario_dict}``.

        A ``"default"`` key, if present, is used for any unmatched instruction.
        """
        default = None
        scenarios = {}
        for key, value in data.items():
            scenario = RecordedScenario.from_dict(value)
            if key == 'default':
                default = scenario
            else:
                scenarios[key] = scenario
        return cls(scenarios, default)

    def register(self, instruction, scenario):
        """Register ``scenario`` for ``instruction`` and return this planner."""
        self._scenarios[instruction] = scenario
        return self

    def plan(self, instruction):
        """Return the recorded plan for ``instruction`` or raise ``KeyError``."""
        scenario = self._scenarios.get(instruction, self._default)
        if scenario is None:
            raise KeyError(
                'no recorded scenario for instruction: %r' % instruction)
        return list(scenario.tool_calls), scenario.final_message


class AgentSession:
    """Runs an instruction by dispatching a planner's tool calls."""

    def __init__(self, dispatcher, planner):
        """Bind a :class:`ToolDispatcher` to a :class:`Planner`."""
        self._dispatcher = dispatcher
        self._planner = planner

    @property
    def dispatcher(self):
        """Return the underlying dispatcher."""
        return self._dispatcher

    def run(self, instruction):
        """Plan and execute ``instruction``, returning a :class:`SessionResult`."""
        calls, final_message = self._planner.plan(instruction)
        transcript = []
        for call in calls:
            result = self._dispatcher.call(call.tool, call.args)
            transcript.append(result.to_dict())
        return SessionResult(
            instruction=instruction,
            transcript=transcript,
            final_message=final_message,
            audit=self._dispatcher.audit.to_list())


# Type alias documenting the recorded-scenario registry shape.
ScenarioMap = Dict[str, RecordedScenario]

__all__ = [
    'AgentSession',
    'Planner',
    'RecordedPlanner',
    'RecordedScenario',
    'ScenarioMap',
    'SessionResult',
    'ToolCall',
]
