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
Tests for the four subagent definitions and their tool scoping.

These assert the least-privilege rule holds -- only the Editor and Repair agents
may mutate the model -- and that the SDK-facing rendering is well formed without
importing the SDK itself.
"""

from urdf_ai_agents.agents.definitions import (
    AGENT_SPECS, sdk_agents, SPEC_BY_SLUG)
from urdf_ai_agents.tools.schemas import qualified_name


def test_all_four_agents_are_defined():
    """The four Milestone 4 subagents are present and uniquely slugged."""
    slugs = {spec.slug for spec in AGENT_SPECS}
    assert slugs == {
        'urdf-editor', 'constraint-validator', 'kinematic-reasoner', 'repair'}


def test_only_editor_and_repair_can_mutate():
    """Read-only agents are denied the mutating apply_model tool."""
    apply_tool = qualified_name('apply_model')
    editors = {'urdf-editor', 'repair'}
    for spec in AGENT_SPECS:
        has_apply = apply_tool in spec.qualified_tools()
        assert has_apply == (spec.slug in editors)


def test_prompts_carry_the_staging_rule():
    """Every agent prompt states the never-write-directly staging discipline."""
    for spec in AGENT_SPECS:
        assert 'stage_edit' in spec.prompt
        assert 'never' in spec.prompt.lower()


def test_sdk_agents_render_camelcase_kwargs():
    """sdk_agents produces AgentDefinition kwargs with qualified tool names."""
    rendered = sdk_agents()
    assert set(rendered) == set(SPEC_BY_SLUG)
    editor = rendered['urdf-editor']
    assert editor['description'] and editor['prompt']
    assert all(t.startswith('mcp__urdf__') for t in editor['tools'])
