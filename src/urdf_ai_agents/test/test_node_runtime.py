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
Tests for the ROS-free helpers of ``ai_agent_node``.

The node's logic (loading URDF, building the dispatcher, replaying a recorded
scenario file) is factored out of ``main`` so it runs without rclpy. These tests
drive that logic directly against a temp scenario file.
"""

import json
import os

import pytest

from urdf_ai_agents.ai_agent_node import build_dispatcher, load_urdf, run_recorded

ARM = ('<robot name="arm">'
       '<link name="base"/><link name="link_1"/><link name="link_2"/>'
       '<joint name="shoulder" type="revolute">'
       '<parent link="base"/><child link="link_1"/><axis xyz="0 0 1"/>'
       '<limit lower="-1.5" upper="1.5" effort="10" velocity="1"/></joint>'
       '<joint name="j2" type="revolute">'
       '<parent link="link_1"/><child link="link_2"/><axis xyz="0 1 0"/>'
       '<limit lower="-1.5" upper="1.5" effort="10" velocity="1"/></joint>'
       '</robot>')

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def test_load_urdf_prefers_robot_description():
    """load_urdf returns the inline description over a path."""
    assert load_urdf(robot_description=ARM) == ARM


def test_load_urdf_requires_a_source():
    """load_urdf raises when given neither a description nor a path."""
    with pytest.raises(ValueError):
        load_urdf()


def test_build_dispatcher_exposes_a_working_toolbox():
    """build_dispatcher returns a dispatcher over the given model."""
    dispatcher = build_dispatcher(ARM)
    result = dispatcher.call('read_urdf')
    assert result.ok and '<robot' in result.data['urdf']


def test_run_recorded_replays_a_scenario_file():
    """run_recorded loads the editor fixture and applies the elbow edit."""
    scenario_file = os.path.join(FIXTURES, 'editor_sessions.json')
    result = run_recorded(
        ARM, scenario_file, 'add a ±90° elbow between link_2 and link_3')
    assert result.applied is True
    assert result.final_message


def test_run_recorded_handles_a_generated_scenario(tmp_path):
    """A minimal scenario written to disk drives a read-only session."""
    path = tmp_path / 'scenario.json'
    scenario = {
        'inspect the model': {
            'tool_calls': [{'tool': 'read_urdf', 'args': {}}],
            'final_message': 'read the model',
        }
    }
    path.write_text(json.dumps(scenario), encoding='utf-8')
    result = run_recorded(ARM, str(path), 'inspect the model')
    assert result.applied is False
    assert result.transcript[0]['tool'] == 'read_urdf'
