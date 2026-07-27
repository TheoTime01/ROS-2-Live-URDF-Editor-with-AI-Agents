"""Milestone 6 stretch extensions built on the deterministic core.

Four cooperating, ROS-independent capabilities that extend the live editor
beyond a single visualized model:

* :mod:`~urdf_live_editor.extensions.ros2_control` — generate ``<ros2_control>``
  URDF blocks and controller-manager YAML from the model's movable joints, and
  validate a hand-written controllers config against the model.
* :mod:`~urdf_live_editor.extensions.gazebo` — generate ``gazebo_ros2_control``
  wiring and a deterministic spawn plan, and check simulation readiness.
* :mod:`~urdf_live_editor.extensions.sessions` — multi-robot / multi-model
  sessions with deterministic URDF namespacing and frame-collision detection.
* :mod:`~urdf_live_editor.extensions.physical_validation` — collision-geometry
  and inertial plausibility validation (mass, positive-definite inertia,
  triangle inequality).

All four share the small :mod:`~urdf_live_editor.extensions.report` primitives
(:class:`Severity`, :class:`Issue`, :class:`Report`) and are fully unit-testable
offline, honoring the project's principle that the AI layer can explain these
results but never fabricate a passing one.
"""

from __future__ import annotations

from .gazebo import (
    SpawnPlan,
    SpawnStep,
    build_spawn_plan,
    check_gazebo_readiness,
    generate_gazebo_ros2_control_block,
)
from .physical_validation import (
    InertialInfo,
    is_positive_definite_3x3,
    symmetric_eigenvalues_3x3,
    validate_physical,
)
from .report import Issue, Report, Severity
from .ros2_control import (
    DEFAULT_HARDWARE_PLUGIN,
    InterfacePlan,
    build_interface_plans,
    embed_ros2_control,
    generate_controller_manager_yaml,
    generate_ros2_control_xml,
    validate_controllers_config,
)
from .sessions import (
    DuplicateSessionError,
    ModelSession,
    SessionRegistry,
    is_valid_namespace,
    namespace_urdf,
)

__all__ = [
    # report primitives
    "Severity",
    "Issue",
    "Report",
    # ros2_control
    "InterfacePlan",
    "build_interface_plans",
    "generate_ros2_control_xml",
    "embed_ros2_control",
    "generate_controller_manager_yaml",
    "validate_controllers_config",
    "DEFAULT_HARDWARE_PLUGIN",
    # gazebo
    "SpawnStep",
    "SpawnPlan",
    "generate_gazebo_ros2_control_block",
    "build_spawn_plan",
    "check_gazebo_readiness",
    # sessions
    "ModelSession",
    "SessionRegistry",
    "namespace_urdf",
    "is_valid_namespace",
    "DuplicateSessionError",
    # physical validation
    "InertialInfo",
    "validate_physical",
    "symmetric_eigenvalues_3x3",
    "is_positive_definite_3x3",
]
