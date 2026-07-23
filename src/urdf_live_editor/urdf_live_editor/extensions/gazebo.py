"""Deterministic Gazebo simulation artifacts for the live-edited model.

This module produces the *non-model* pieces needed to simulate the current URDF
in Gazebo, and checks that the model is actually simulatable, without launching
anything:

* :func:`generate_gazebo_ros2_control_block` — the ``<gazebo>`` block wiring the
  ``gazebo_ros2_control`` plugin to a controllers YAML, so the same controllers
  validated in :mod:`~urdf_live_editor.extensions.ros2_control` drive the sim.
* :func:`build_spawn_plan` — an ordered, deterministic description of the steps a
  launch file must perform to bring the model up in Gazebo
  (``robot_state_publisher`` → ``spawn_entity`` → controller spawners).
* :func:`check_gazebo_readiness` — a report combining the physical checks that
  Gazebo specifically cares about (every simulated link needs mass; a link with
  no collision will pass through the world) with Gazebo-specific advice.

Deterministic and offline like the rest of the extensions layer: it returns
strings, dataclasses, and reports; the actual ``ros_gz``/``gazebo_ros`` launch
wiring is a thin wrapper that consumes these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .physical_validation import validate_physical
from .report import Report, Severity, _Builder

__all__ = [
    "SpawnStep",
    "SpawnPlan",
    "generate_gazebo_ros2_control_block",
    "build_spawn_plan",
    "check_gazebo_readiness",
    "DEFAULT_CONTROLLERS_PATH",
]

DEFAULT_CONTROLLERS_PATH = "config/controllers.yaml"


def generate_gazebo_ros2_control_block(
    *,
    controllers_path: str = DEFAULT_CONTROLLERS_PATH,
    parameters_package: Optional[str] = None,
    indent: str = "  ",
) -> str:
    """Generate the ``<gazebo>`` block that loads ``gazebo_ros2_control``.

    ``controllers_path`` is the path (or ``package``-relative path if
    ``parameters_package`` is given) to the controller-manager YAML produced by
    :func:`~urdf_live_editor.extensions.ros2_control.generate_controller_manager_yaml`.
    """
    if parameters_package:
        params_ref = f"$(find {parameters_package})/{controllers_path}"
    else:
        params_ref = controllers_path
    lines = [
        "<gazebo>",
        f'{indent}<plugin filename="libgazebo_ros2_control.so" '
        'name="gazebo_ros2_control">',
        f"{indent}{indent}<parameters>{params_ref}</parameters>",
        f"{indent}</plugin>",
        "</gazebo>",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class SpawnStep:
    """A single ordered action in a Gazebo bring-up sequence."""

    order: int
    kind: str            # e.g. "robot_state_publisher", "spawn_entity", "spawner"
    description: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order": self.order,
            "kind": self.kind,
            "description": self.description,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class SpawnPlan:
    """An ordered, deterministic Gazebo bring-up plan."""

    entity_name: str
    steps: List[SpawnStep] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_name": self.entity_name,
            "steps": [s.to_dict() for s in self.steps],
        }


def build_spawn_plan(
    *,
    entity_name: str,
    controllers: Optional[List[str]] = None,
    namespace: Optional[str] = None,
    world: str = "empty.sdf",
    spawn_pose: Optional[Dict[str, float]] = None,
) -> SpawnPlan:
    """Build the ordered steps to spawn the model and start its controllers.

    The ordering encodes Gazebo's hard requirements: ``robot_state_publisher``
    must publish ``robot_description`` before ``spawn_entity`` reads it, and the
    entity must exist before any controller spawner can configure the plugin.
    Controllers are always started with ``joint_state_broadcaster`` first.
    """
    ns_prefix = f"/{namespace}" if namespace else ""
    steps: List[SpawnStep] = []
    steps.append(
        SpawnStep(
            order=1,
            kind="gazebo",
            description=f"launch Gazebo with world '{world}'",
            detail={"world": world},
        )
    )
    steps.append(
        SpawnStep(
            order=2,
            kind="robot_state_publisher",
            description="publish robot_description and TF",
            detail={"namespace": ns_prefix or "/"},
        )
    )
    steps.append(
        SpawnStep(
            order=3,
            kind="spawn_entity",
            description=f"spawn '{entity_name}' into Gazebo from robot_description",
            detail={
                "entity": entity_name,
                "pose": spawn_pose or {"x": 0.0, "y": 0.0, "z": 0.0},
            },
        )
    )

    ordered_controllers: List[str] = ["joint_state_broadcaster"]
    for name in controllers or []:
        if name not in ordered_controllers:
            ordered_controllers.append(name)

    for offset, controller in enumerate(ordered_controllers):
        steps.append(
            SpawnStep(
                order=4 + offset,
                kind="spawner",
                description=f"start controller '{controller}'",
                detail={"controller": controller, "namespace": ns_prefix or "/"},
            )
        )

    return SpawnPlan(entity_name=entity_name, steps=steps)


def check_gazebo_readiness(urdf_xml: str) -> Report:
    """Report whether the model is ready to simulate in Gazebo.

    Gazebo drops (or warns about) links without mass and cannot collide links
    without ``<collision>`` geometry, so simulation readiness is a *stricter*
    reading of the physical-validation report: the "no collision" finding is
    promoted to a warning here, and physical ERRORs are surfaced unchanged.
    """
    physical = validate_physical(urdf_xml, require_collision=False)
    out = _Builder("gazebo_readiness")

    for issue in physical.issues:
        if issue.code == "collision_missing":
            # Gazebo-specific: massless-but-visible links pass through the world.
            out.warn(
                "gazebo_collision_missing",
                f"{issue.message} (Gazebo objects will pass through it)",
                issue.subject,
            )
        elif issue.code == "inertial_missing" and issue.severity is Severity.WARNING:
            out.error(
                "gazebo_inertial_missing",
                f"link '{issue.subject}' has no inertial; Gazebo will drop the "
                "link from the simulation",
                issue.subject,
            )
        else:
            out.add(issue.severity, issue.code, issue.message, issue.subject)

    return out.build()
