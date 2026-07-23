"""Deterministic ``ros2_control`` generation and validation (Milestone 6).

Once a URDF can be edited live, the natural next step is to *drive* the edited
joints with real controllers. ``ros2_control`` needs two artifacts that must
stay consistent with the model at all times:

1. a ``<ros2_control>`` block **inside the URDF** declaring, per joint, the
   hardware command/state interfaces, and
2. a **controller-manager YAML** listing the controllers and the joints each
   one owns.

If either drifts from the model (a joint is renamed, retyped to ``fixed``, or a
new joint is added) the controller manager fails to configure, often with an
opaque runtime error. This module removes that class of failure by
*generating* both artifacts from the model deterministically, and by
*validating* a hand-written controllers config against the model.

As with the rest of the project, nothing here talks to ROS or an LLM. It works
on a :class:`~urdf_live_editor.integration.launch_sync.ModelSummary` (or a raw
URDF string) and returns plain strings / dicts / reports, so an agent can
explain the output but can never invent an interface the model does not support.

Interface conventions
----------------------
* ``revolute`` / ``prismatic`` joints → a ``position`` command interface plus
  ``position`` and ``velocity`` state interfaces (the common default). Command
  interfaces can be overridden per call.
* ``continuous`` joints → a ``velocity`` command interface (no position limit to
  command against) plus ``position`` and ``velocity`` state interfaces.
* ``fixed`` and other non-movable joints are never given interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..integration.launch_sync import ModelSummary, extract_model_summary
from .report import Report, _Builder

__all__ = [
    "InterfacePlan",
    "default_interfaces",
    "build_interface_plans",
    "generate_ros2_control_xml",
    "embed_ros2_control",
    "generate_controller_manager_yaml",
    "validate_controllers_config",
    "DEFAULT_HARDWARE_PLUGIN",
]

# The mock hardware is the standard offline default: it lets ``ros2_control``
# load and echo commands with no real robot, which is exactly what a live
# editor wants for a dry run.
DEFAULT_HARDWARE_PLUGIN = "mock_components/GenericSystem"


@dataclass(frozen=True)
class InterfacePlan:
    """The command/state interfaces a single joint should expose."""

    joint: str
    joint_type: str
    command_interfaces: List[str] = field(default_factory=list)
    state_interfaces: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "joint": self.joint,
            "joint_type": self.joint_type,
            "command_interfaces": list(self.command_interfaces),
            "state_interfaces": list(self.state_interfaces),
        }


def default_interfaces(joint_type: str) -> InterfacePlan:
    """Return the conventional interface set for a movable joint type."""
    jtype = joint_type.strip().lower()
    if jtype == "continuous":
        command = ["velocity"]
    else:  # revolute / prismatic
        command = ["position"]
    return InterfacePlan(
        joint="",
        joint_type=jtype,
        command_interfaces=command,
        state_interfaces=["position", "velocity"],
    )


def _as_model(model: Any) -> ModelSummary:
    if isinstance(model, ModelSummary):
        return model
    if isinstance(model, str):
        return extract_model_summary(model)
    raise TypeError("model must be a ModelSummary or a URDF string")


def build_interface_plans(
    model: Any,
    *,
    command_overrides: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[InterfacePlan]:
    """Build one :class:`InterfacePlan` per movable joint, in stable order.

    ``command_overrides`` maps a joint name to an explicit list of command
    interfaces, overriding the type-based default for that joint.
    """
    summary = _as_model(model)
    overrides = {k: list(v) for k, v in (command_overrides or {}).items()}
    plans: List[InterfacePlan] = []
    for name in summary.joint_names(movable_only=True):
        info = summary.joints[name]
        base = default_interfaces(info.type)
        command = overrides.get(name, base.command_interfaces)
        plans.append(
            InterfacePlan(
                joint=name,
                joint_type=info.type,
                command_interfaces=list(command),
                state_interfaces=list(base.state_interfaces),
            )
        )
    return plans


def generate_ros2_control_xml(
    model: Any,
    *,
    name: str = "RobotSystem",
    hardware_plugin: str = DEFAULT_HARDWARE_PLUGIN,
    hardware_parameters: Optional[Mapping[str, str]] = None,
    command_overrides: Optional[Mapping[str, Sequence[str]]] = None,
    indent: str = "  ",
) -> str:
    """Generate a ``<ros2_control>`` XML block for the model's movable joints.

    The output is deterministic (stable joint and interface ordering) and
    ready to be inserted into a URDF via :func:`embed_ros2_control`.
    """
    plans = build_interface_plans(model, command_overrides=command_overrides)
    lines: List[str] = []
    lines.append(f'<ros2_control name="{name}" type="system">')
    lines.append(f"{indent}<hardware>")
    lines.append(f'{indent}{indent}<plugin>{hardware_plugin}</plugin>')
    for key in sorted(hardware_parameters or {}):
        val = hardware_parameters[key]
        lines.append(f'{indent}{indent}<param name="{key}">{val}</param>')
    lines.append(f"{indent}</hardware>")
    for plan in plans:
        lines.append(f'{indent}<joint name="{plan.joint}">')
        for iface in plan.command_interfaces:
            lines.append(f'{indent}{indent}<command_interface name="{iface}"/>')
        for iface in plan.state_interfaces:
            lines.append(f'{indent}{indent}<state_interface name="{iface}"/>')
        lines.append(f"{indent}</joint>")
    lines.append("</ros2_control>")
    return "\n".join(lines)


def embed_ros2_control(urdf_xml: str, control_xml: str) -> str:
    """Return a new URDF string with ``control_xml`` inserted before ``</robot>``.

    The input string is not mutated. Raises :class:`ValueError` if the URDF has
    no closing ``</robot>`` tag.
    """
    marker = "</robot>"
    idx = urdf_xml.rfind(marker)
    if idx == -1:
        raise ValueError("URDF has no closing </robot> tag")
    block = "\n".join("  " + line for line in control_xml.splitlines())
    return urdf_xml[:idx] + block + "\n" + urdf_xml[idx:]


def generate_controller_manager_yaml(
    model: Any,
    *,
    update_rate: int = 100,
    arm_controller_name: str = "joint_trajectory_controller",
    namespace: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a controller-manager parameter dict (YAML-serializable).

    Produces a ``controller_manager`` block declaring a
    ``joint_state_broadcaster`` and a trajectory/velocity controller that owns
    every movable joint, plus that controller's own parameter block listing its
    joints and interfaces.
    """
    plans = build_interface_plans(model)
    joints = [p.joint for p in plans]

    # If any joint is continuous-only (velocity command), a trajectory
    # controller cannot own it; fall back to a velocity controller type.
    has_velocity_only = any("position" not in p.command_interfaces for p in plans)
    controller_type = (
        "velocity_controllers/JointGroupVelocityController"
        if has_velocity_only
        else "joint_trajectory_controller/JointTrajectoryController"
    )

    cm_params: Dict[str, Any] = {
        "update_rate": update_rate,
        "joint_state_broadcaster": {
            "type": "joint_state_broadcaster/JointStateBroadcaster",
        },
        arm_controller_name: {"type": controller_type},
    }

    controller_block: Dict[str, Any] = {"joints": joints}
    if not has_velocity_only:
        controller_block["command_interfaces"] = ["position"]
        controller_block["state_interfaces"] = ["position", "velocity"]

    config: Dict[str, Any] = {
        "controller_manager": {"ros__parameters": cm_params},
        arm_controller_name: {"ros__parameters": controller_block},
    }
    if namespace:
        return {namespace: config}
    return config


def _controlled_joints(config: Mapping[str, Any]) -> Dict[str, List[str]]:
    """Extract ``{controller_name: [joint, ...]}`` from a controllers config.

    Understands both the flat shape produced by
    :func:`generate_controller_manager_yaml` and a namespaced wrapper.
    """
    # Unwrap a single namespace layer if present.
    if "controller_manager" not in config and len(config) == 1:
        (only,) = config.values()
        if isinstance(only, Mapping) and "controller_manager" in only:
            config = only

    result: Dict[str, List[str]] = {}
    for key, value in config.items():
        if key == "controller_manager" or not isinstance(value, Mapping):
            continue
        params = value.get("ros__parameters")
        if not isinstance(params, Mapping):
            continue
        raw = params.get("joints")
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            result[str(key)] = [str(j) for j in raw]
    return result


def validate_controllers_config(model: Any, config: Mapping[str, Any]) -> Report:
    """Validate that a controllers config is consistent with the model.

    Findings:

    * a joint owned by a controller but absent from the model, or present but
      not movable  → ERROR (the controller manager will fail to claim it);
    * a movable joint owned by **no** controller  → WARNING (it will not be
      commandable);
    * the same joint owned by more than one controller  → ERROR (interface
      contention).
    """
    summary = _as_model(model)
    movable = set(summary.joint_names(movable_only=True))
    out = _Builder("ros2_control_config")

    controlled = _controlled_joints(config)
    seen: Dict[str, str] = {}
    covered: set = set()

    for controller in sorted(controlled):
        for joint in controlled[controller]:
            covered.add(joint)
            if joint not in summary.joints:
                out.error(
                    "joint_not_in_model",
                    f"controller '{controller}' owns joint '{joint}' which is "
                    "not in the model",
                    joint,
                )
            elif joint not in movable:
                jtype = summary.joints[joint].type
                out.error(
                    "joint_not_movable",
                    f"controller '{controller}' owns joint '{joint}' which is "
                    f"'{jtype}' and has no runtime DOF",
                    joint,
                )
            if joint in seen:
                out.error(
                    "joint_double_owned",
                    f"joint '{joint}' is owned by both '{seen[joint]}' and "
                    f"'{controller}'",
                    joint,
                )
            else:
                seen[joint] = controller

    for joint in sorted(movable - covered):
        out.warn(
            "joint_uncontrolled",
            f"movable joint '{joint}' is not owned by any controller",
            joint,
        )

    return out.build()
