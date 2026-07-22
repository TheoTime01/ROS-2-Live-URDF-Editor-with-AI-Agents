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
Tests for the deterministic explanation and repair knowledge base.

These lock the substrate the Validator, Reasoner, and Repair agents stand on:
every issue code explains, degeneracies are named, and the suggested repairs
turn a broken model into a valid one without any API call.
"""

from urdf_ai_agents.explanations import (
    describe_degeneracies, explain_code, explain_result, suggest_repairs)
from urdf_live_editor.model.edit_ops import operations_from_dicts
from urdf_live_editor.model_update_coordinator_node import (
    ModelUpdateCoordinator)
from urdf_live_editor.validation.engine import validate_model, validate_urdf_string

BROKEN = ('<robot name="r"><link name="base"/><link name="l1"/>'
          '<joint name="j1" type="revolute">'
          '<parent link="base"/><child link="l1"/>'
          '<limit lower="1" upper="-1" effort="-5" velocity="0"/></joint>'
          '</robot>')

DEGENERATE = ('<robot name="r"><link name="base"/><link name="l1"/>'
              '<link name="l2"/><link name="l3"/>'
              '<joint name="spin" type="continuous">'
              '<parent link="base"/><child link="l1"/><axis xyz="0 0 1"/>'
              '<limit lower="-1" upper="1" effort="5" velocity="1"/></joint>'
              '<joint name="weld" type="fixed">'
              '<parent link="l1"/><child link="l2"/><axis xyz="0 0 1"/></joint>'
              '<joint name="rot" type="revolute">'
              '<parent link="l2"/><child link="l3"/><axis xyz="0 0 1"/>'
              '<limit lower="-1" upper="1" effort="5" velocity="1"/></joint>'
              '</robot>')


def test_explain_code_known_and_unknown():
    """A known code explains specifically; an unknown one falls back."""
    explanation, repair = explain_code('JOINT_LIMIT_INVERTED')
    assert 'lower limit exceeds' in explanation
    assert 'lower <= upper' in repair
    fallback, _ = explain_code('NOT_A_REAL_CODE')
    assert 'No detailed explanation' in fallback


def test_explain_result_covers_every_issue():
    """explain_result yields one explained record per issue, in order."""
    _, result = validate_urdf_string(BROKEN)
    explained = explain_result(result)
    assert [e['code'] for e in explained] == result.codes
    assert all(e['explanation'] and e['repair_hint'] for e in explained)


def test_suggest_repairs_makes_a_broken_model_valid():
    """The proposed repairs, applied, turn the broken model valid."""
    model, result = validate_urdf_string(BROKEN)
    repairs = suggest_repairs(model, result)
    coordinator = ModelUpdateCoordinator(model)
    outcome = coordinator.apply(operations_from_dicts(repairs))
    assert outcome.applied is True
    assert validate_model(coordinator.current_version.model).is_valid


def test_suggest_repairs_defaults_axis_and_orders_limits():
    """The repair for j1 sets a default axis and orders the limits."""
    model, result = validate_urdf_string(BROKEN)
    repairs = suggest_repairs(model, result)
    axis_op = next(r for r in repairs if r['op'] == 'set_joint_axis')
    limit_op = next(r for r in repairs if r['op'] == 'set_joint_limit')
    assert axis_op['axis'] == [0.0, 0.0, 1.0]
    assert limit_op['lower'] <= limit_op['upper']
    assert limit_op['effort'] > 0 and limit_op['velocity'] > 0


def test_describe_degeneracies_names_each_kind():
    """Degeneracy notes flag the fixed axis, the ignored bounds, and the DOF."""
    model, _ = validate_urdf_string(DEGENERATE)
    notes = describe_degeneracies(model)
    text = ' '.join(notes)
    assert 'no kinematic effect' in text
    assert 'spins freely and ignores' in text
    assert 'actuated degree' in text
