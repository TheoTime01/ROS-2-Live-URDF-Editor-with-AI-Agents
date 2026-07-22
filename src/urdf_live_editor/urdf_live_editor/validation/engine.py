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
Composition point for the deterministic validation checks.

:func:`validate_model` runs the schema, topology, and joint-rule checks over a
parsed model and merges their issues. :func:`validate_urdf_string` adds the
well-formedness gate in front, so a caller can hand it raw ``robot_description``
text and get back either a parsed model plus its verdict, or a schema error and
no model.
"""

from urdf_live_editor.model.robot_model import RobotModel
from urdf_live_editor.validation import joint_rules, schema, topology
from urdf_live_editor.validation.result import ValidationResult


def validate_model(model):
    """Run every deterministic check over ``model`` and merge the results."""
    result = ValidationResult.ok()
    result.extend(schema.check(model))
    result.extend(topology.check(model))
    result.extend(joint_rules.check(model))
    return result


def validate_urdf_string(xml_str):
    """Validate raw URDF text, returning ``(model_or_none, result)``."""
    well_formed = schema.check_well_formed(xml_str)
    if not well_formed.is_valid:
        return None, well_formed
    model = RobotModel.from_string(xml_str)
    return model, validate_model(model)
