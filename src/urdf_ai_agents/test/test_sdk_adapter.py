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
Tests for the live SDK adapter's SDK-free surface.

The adapter must import and behave gracefully whether or not
``claude_agent_sdk`` is installed: its pure helpers work everywhere, and the
SDK-dependent builders raise a clear error (rather than an ImportError) when the
SDK is missing. The end-to-end live path is covered separately by the opt-in
suite in ``test_live_sdk``.
"""

import pytest

from urdf_ai_agents import sdk_adapter
from urdf_ai_agents.tools.schemas import qualified_name
from urdf_ai_agents.tools.toolbox import UrdfToolbox

VALID = ('<robot name="r"><link name="base"/><link name="l1"/>'
         '<joint name="j1" type="revolute">'
         '<parent link="base"/><child link="l1"/><axis xyz="0 0 1"/>'
         '<limit lower="-1" upper="1" effort="5" velocity="1"/></joint></robot>')


def test_sdk_available_returns_bool():
    """sdk_available answers without raising, whatever the environment."""
    assert isinstance(sdk_adapter.sdk_available(), bool)


def test_spec_for_maps_qualified_names():
    """_spec_for resolves qualified tool names and ignores foreign ones."""
    spec = sdk_adapter._spec_for(qualified_name('apply_model'))
    assert spec is not None and spec.name == 'apply_model'
    assert sdk_adapter._spec_for('mcp__other__thing') is None
    assert sdk_adapter._spec_for('Bash') is None


def test_parse_tool_output_reads_status_and_body():
    """_parse_tool_output pulls status and JSON body from an SDK result."""
    ok = {'content': [{'type': 'text', 'text': '{"applied": true}'}]}
    status, body = sdk_adapter._parse_tool_output(ok)
    assert status == 200 and body['applied'] is True
    err = {'content': [{'type': 'text', 'text': '{}'}], 'isError': True}
    status, _ = sdk_adapter._parse_tool_output(err)
    assert status == 400


def test_builders_error_clearly_when_sdk_missing():
    """Without the SDK, the builders raise RuntimeError, not ImportError."""
    if sdk_adapter.sdk_available():
        pytest.skip('claude_agent_sdk is installed; missing-SDK path N/A')
    box = UrdfToolbox.from_urdf(VALID)
    with pytest.raises(RuntimeError):
        sdk_adapter.build_mcp_server(box)
    with pytest.raises(RuntimeError):
        sdk_adapter.build_agent_options(box)


def test_agent_options_assemble_when_sdk_present():
    """With the SDK installed, options carry the tools, hooks, and agents."""
    if not sdk_adapter.sdk_available():
        pytest.skip('claude_agent_sdk not installed')
    box = UrdfToolbox.from_urdf(VALID)
    options, audit = sdk_adapter.build_agent_options(box)
    assert options.agents and 'urdf-editor' in options.agents
    assert options.allowed_tools
    assert audit is not None
