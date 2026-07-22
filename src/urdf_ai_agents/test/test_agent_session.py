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
The Milestone 4 acceptance proof, run deterministically from recordings.

Two end-to-end flows drive the whole AI runtime -- planner, dispatcher, mutation
guard, and audit trail -- with the tool arguments supplied by a recorded fixture
(the JSON an LLM would emit) so no API is touched:

* the URDF Editor Agent turns "add a +/-90 degree elbow between link_2 and
  link_3" into a validated, applied edit;
* the Repair Agent diagnoses a broken URDF and repairs it to a valid model.

A third test confirms the guard still fires inside a session: a recorded plan
that tries to apply without staging is blocked.
"""

import json
import os

from urdf_ai_agents.dispatch import ToolDispatcher
from urdf_ai_agents.session import (
    AgentSession, RecordedPlanner, RecordedScenario, ToolCall)
from urdf_ai_agents.tools.toolbox import UrdfToolbox

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')

ARM = ('<robot name="arm">'
       '<link name="base"/><link name="link_1"/><link name="link_2"/>'
       '<joint name="shoulder" type="revolute">'
       '<parent link="base"/><child link="link_1"/><axis xyz="0 0 1"/>'
       '<limit lower="-1.5" upper="1.5" effort="10" velocity="1"/></joint>'
       '<joint name="j2" type="revolute">'
       '<parent link="link_1"/><child link="link_2"/><axis xyz="0 1 0"/>'
       '<limit lower="-1.5" upper="1.5" effort="10" velocity="1"/></joint>'
       '</robot>')

BROKEN = ('<robot name="r"><link name="base"/><link name="l1"/>'
          '<joint name="j1" type="revolute">'
          '<parent link="base"/><child link="l1"/>'
          '<limit lower="1" upper="-1" effort="-5" velocity="0"/></joint>'
          '</robot>')


def _planner(fixture_name):
    """Load a recorded planner from a fixture file under ``fixtures/``."""
    with open(os.path.join(FIXTURES, fixture_name), encoding='utf-8') as fh:
        return RecordedPlanner.from_dict(json.load(fh))


def test_editor_adds_a_validated_applied_elbow():
    """The elbow instruction produces a validated, applied edit."""
    box = UrdfToolbox.from_urdf(ARM)
    session = AgentSession(ToolDispatcher(box), _planner('editor_sessions.json'))

    result = session.run('add a ±90° elbow between link_2 and link_3')

    assert result.applied is True
    assert result.blocked_calls == []
    _, model = box.read_urdf()
    assert model['version']['index'] == 1
    assert model['validation']['is_valid'] is True
    assert 'link_3' in model['urdf']
    assert 'elbow' in result.final_message.lower()
    # The applied edit is captured in the audit trail with its diff.
    applied = [e for e in result.audit if e['tool'] == 'apply_model']
    assert applied and applied[0]['diff']['added_links'] == ['link_3']


def test_repair_diagnoses_and_fixes_a_broken_model():
    """A broken URDF is loaded, diagnosed, and repaired to a valid model."""
    box = UrdfToolbox.from_urdf(BROKEN, require_valid=False)
    session = AgentSession(ToolDispatcher(box), _planner('repair_sessions.json'))

    # Before repair the model is invalid.
    _, before = box.read_urdf()
    assert before['validation']['is_valid'] is False

    result = session.run('fix the broken shoulder joint')

    assert result.applied is True
    _, after = box.read_urdf()
    assert after['validation']['is_valid'] is True
    assert 'repaired' in result.final_message.lower()


def test_session_guard_blocks_an_unstaged_apply():
    """A recorded plan that skips staging is blocked inside the session."""
    box = UrdfToolbox.from_urdf(ARM)
    ops = [{'op': 'add_link', 'name': 'rogue'}]
    scenario = RecordedScenario(
        [ToolCall('apply_model', {'operations': ops})], 'tried to skip staging')
    planner = RecordedPlanner().register('skip staging', scenario)
    session = AgentSession(ToolDispatcher(box), planner)

    result = session.run('skip staging')

    assert result.applied is False
    assert len(result.blocked_calls) == 1
    _, model = box.read_urdf()
    assert 'rogue' not in model['urdf']
