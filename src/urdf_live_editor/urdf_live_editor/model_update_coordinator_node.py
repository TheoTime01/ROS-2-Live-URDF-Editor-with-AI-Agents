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
Stage -> validate -> apply/reject pipeline for model updates.

:class:`ModelUpdateCoordinator` is the trusted heart of the deterministic core.
It owns the version store and is the only path by which the model changes: an
edit is applied to a *copy* of the current model, the candidate is validated,
and only a candidate with no error-severity issues is committed as a new
version. A failing candidate is rejected and the live model is untouched. This
is the interface a human, the web API, and later the AI layer all share, so the
AI can never bypass validation.

The pipeline logic is plain Python and fully testable offline; ``main`` only
wraps it in a ROS 2 node.
"""

from dataclasses import dataclass
from typing import Optional

from urdf_live_editor.model.edit_ops import apply_operations, EditError
from urdf_live_editor.model.robot_model import RobotModel
from urdf_live_editor.model.version_store import Version, VersionStore
from urdf_live_editor.validation.engine import validate_model
from urdf_live_editor.validation.result import ValidationResult


@dataclass
class StageResult:
    """The outcome of staging and validating a candidate without applying it."""

    candidate: Optional[RobotModel]
    result: ValidationResult
    error: Optional[str] = None

    @property
    def is_valid(self):
        """Return ``True`` when a candidate was built and passed validation."""
        return self.candidate is not None and self.result.is_valid


@dataclass
class ApplyResult:
    """The outcome of an apply attempt."""

    applied: bool
    result: ValidationResult
    version: Optional[Version] = None
    error: Optional[str] = None


class ModelUpdateCoordinator:
    """Owns the version store and enforces stage -> validate -> apply."""

    def __init__(self, model, label='initial'):
        """Seed the coordinator with an initial (already-parsed) model."""
        self._store = VersionStore(model, label)

    @classmethod
    def from_urdf(cls, xml_str, label='initial'):
        """Build a coordinator from a URDF string, requiring it to be valid."""
        from urdf_live_editor.validation.engine import validate_urdf_string
        model, result = validate_urdf_string(xml_str)
        if model is None or not result.is_valid:
            raise ValueError(
                'initial model failed validation: %s'
                % '; '.join(str(i) for i in result.errors))
        return cls(model, label)

    @property
    def store(self):
        """Return the underlying version store."""
        return self._store

    @property
    def current_version(self):
        """Return the current version."""
        return self._store.current

    def current_model(self):
        """Return an editable copy of the current model."""
        return self._store.current_model()

    def current_urdf(self):
        """Return the current model serialized as URDF."""
        return self._store.current.to_urdf()

    def stage(self, operations):
        """Apply ``operations`` to a candidate and validate it, no commit."""
        try:
            candidate = apply_operations(self.current_model(), operations)
        except EditError as exc:
            result = ValidationResult.ok().add_error('EDIT_ERROR', str(exc))
            return StageResult(None, result, error=str(exc))
        return StageResult(candidate, validate_model(candidate))

    def apply(self, operations, label=None):
        """Stage, validate, and commit ``operations`` if the candidate holds."""
        staged = self.stage(operations)
        if staged.candidate is None:
            return ApplyResult(False, staged.result, error=staged.error)
        if not staged.result.is_valid:
            return ApplyResult(False, staged.result)
        version = self._store.commit(
            staged.candidate,
            operations=[op.to_dict() for op in operations],
            label=label)
        return ApplyResult(True, staged.result, version=version)

    def rollback(self, target_index):
        """Roll back to an earlier version, appending it as the new current."""
        return self._store.rollback(target_index)

    def validate_current(self):
        """Validate the current model (it should always be valid)."""
        return validate_model(self._store.current.model)

    def history(self):
        """Return the full version history."""
        return self._store.history()

    def audit_log(self):
        """Return the audit log of every version and its diff."""
        return self._store.audit_log()


def main(args=None):
    """Start the model update coordinator node and spin until shutdown."""
    import rclpy
    from rclpy.node import Node

    rclpy.init(args=args)
    node = Node('model_update_coordinator_node')
    node.get_logger().info(
        'model_update_coordinator_node started; '
        'stage -> validate -> apply/reject pipeline ready.')
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
