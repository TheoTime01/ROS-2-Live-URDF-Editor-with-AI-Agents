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
Opt-in live-SDK suite: really call Claude through the Agent SDK.

Every test here is skipped unless the ``claude_agent_sdk`` package is installed
*and* ``URDF_AI_LIVE=1`` is set in the environment, so CI (which has neither)
stays fully deterministic and offline. Set both, with a configured API key, to
exercise the real Editor agent against the live model.
"""

import asyncio
import os

import pytest

from urdf_ai_agents import sdk_adapter
from urdf_ai_agents.tools.toolbox import UrdfToolbox

LIVE = os.environ.get('URDF_AI_LIVE') == '1' and sdk_adapter.sdk_available()

pytestmark = pytest.mark.skipif(
    not LIVE, reason='live SDK suite is opt-in (set URDF_AI_LIVE=1 with the '
                     'SDK installed and an API key configured)')

ARM = ('<robot name="arm">'
       '<link name="base"/><link name="link_1"/><link name="link_2"/>'
       '<joint name="shoulder" type="revolute">'
       '<parent link="base"/><child link="link_1"/><axis xyz="0 0 1"/>'
       '<limit lower="-1.5" upper="1.5" effort="10" velocity="1"/></joint>'
       '<joint name="j2" type="revolute">'
       '<parent link="link_1"/><child link="link_2"/><axis xyz="0 1 0"/>'
       '<limit lower="-1.5" upper="1.5" effort="10" velocity="1"/></joint>'
       '</robot>')


def test_live_editor_applies_an_elbow():
    """A live Editor run stages and applies a validated elbow edit."""
    box = UrdfToolbox.from_urdf(ARM)
    asyncio.run(sdk_adapter.run_live(
        'Add a revolute elbow joint (plus or minus 90 degrees) between '
        'link_2 and a new link_3.', box, agent='urdf-editor'))
    _, model = box.read_urdf()
    assert model['validation']['is_valid'] is True
    assert 'link_3' in model['urdf']
