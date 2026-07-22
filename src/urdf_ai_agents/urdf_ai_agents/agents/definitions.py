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
Declarative definitions of the four Milestone 4 subagents.

An :class:`AgentSpec` is an SDK-agnostic description of one subagent: its slug,
one-line purpose, system prompt, and the subset of URDF tools it may call. The
specs are plain data so they can be unit-tested without the Claude Agent SDK;
:meth:`AgentSpec.to_sdk_kwargs` renders the camelCase keyword arguments the
SDK's ``AgentDefinition`` expects, and :mod:`urdf_ai_agents.sdk_adapter` turns
the collection into the ``agents=`` mapping for a live run.

Each agent is scoped to the least tools it needs: only the Editor and Repair
agents get the mutating ``apply_model``; the read-only Validator and Reasoner
cannot change the model at all.
"""

from dataclasses import dataclass
from typing import List, Optional

from urdf_ai_agents.prompts import system_prompts
from urdf_ai_agents.tools.schemas import qualified_name


@dataclass(frozen=True)
class AgentSpec:
    """One subagent: its slug, description, prompt, and permitted tools."""

    slug: str
    description: str
    prompt: str
    tools: List[str]
    model: Optional[str] = None

    def qualified_tools(self):
        """Return the SDK-qualified (``mcp__urdf__*``) names of its tools."""
        return [qualified_name(tool) for tool in self.tools]

    def to_sdk_kwargs(self):
        """Return kwargs for the SDK's ``AgentDefinition`` (camelCase keys)."""
        kwargs = {
            'description': self.description,
            'prompt': self.prompt,
            'tools': self.qualified_tools(),
        }
        if self.model is not None:
            kwargs['model'] = self.model
        return kwargs


_READ_TOOLS = ['read_urdf', 'describe_joint', 'validate_model']

EDITOR = AgentSpec(
    slug='urdf-editor',
    description='Translate a natural-language instruction into a validated, '
                'applied URDF edit.',
    prompt=system_prompts.EDITOR_PROMPT,
    tools=_READ_TOOLS + ['stage_edit', 'apply_model'])

VALIDATOR = AgentSpec(
    slug='constraint-validator',
    description='Explain URDF validation failures in human terms; never '
                'mutates the model.',
    prompt=system_prompts.VALIDATOR_PROMPT,
    tools=list(_READ_TOOLS))

REASONER = AgentSpec(
    slug='kinematic-reasoner',
    description='Explain what a model does and where it is kinematically '
                'degenerate; read-only.',
    prompt=system_prompts.REASONER_PROMPT,
    tools=['read_urdf', 'describe_joint'])

REPAIR = AgentSpec(
    slug='repair',
    description='Diagnose a malformed URDF and apply a minimal set of '
                'suggested repairs.',
    prompt=system_prompts.REPAIR_PROMPT,
    tools=_READ_TOOLS + ['stage_edit', 'apply_model'])

AGENT_SPECS = (EDITOR, VALIDATOR, REASONER, REPAIR)

SPEC_BY_SLUG = {spec.slug: spec for spec in AGENT_SPECS}


def sdk_agents():
    """Return ``{slug: sdk_kwargs}`` for every agent, for the SDK adapter."""
    return {spec.slug: spec.to_sdk_kwargs() for spec in AGENT_SPECS}
