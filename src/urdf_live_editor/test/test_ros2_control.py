"""Tests for deterministic ros2_control generation and validation."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from urdf_live_editor.extensions.ros2_control import (
    DEFAULT_HARDWARE_PLUGIN,
    build_interface_plans,
    embed_ros2_control,
    generate_controller_manager_yaml,
    generate_ros2_control_xml,
    validate_controllers_config,
)
from urdf_live_editor.integration.launch_sync import extract_model_summary

MIXED_URDF = """
<robot name="arm">
  <link name="base_link"/><link name="l1"/><link name="l2"/><link name="l3"/>
  <link name="tool"/>
  <joint name="shoulder" type="revolute">
    <parent link="base_link"/><child link="l1"/>
    <axis xyz="0 0 1"/><limit lower="-3" upper="3"/>
  </joint>
  <joint name="elbow" type="prismatic">
    <parent link="l1"/><child link="l2"/>
    <axis xyz="0 1 0"/><limit lower="0" upper="0.3"/>
  </joint>
  <joint name="wrist" type="continuous">
    <parent link="l2"/><child link="l3"/><axis xyz="1 0 0"/>
  </joint>
  <joint name="tool_mount" type="fixed">
    <parent link="l3"/><child link="tool"/>
  </joint>
</robot>
"""

REVOLUTE_ONLY_URDF = """
<robot name="arm">
  <link name="base_link"/><link name="l1"/><link name="l2"/>
  <joint name="j1" type="revolute">
    <parent link="base_link"/><child link="l1"/>
    <axis xyz="0 0 1"/><limit lower="-1" upper="1"/>
  </joint>
  <joint name="j2" type="revolute">
    <parent link="l1"/><child link="l2"/>
    <axis xyz="0 1 0"/><limit lower="-1" upper="1"/>
  </joint>
</robot>
"""


# -- interface plans ------------------------------------------------------
def test_interface_plans_by_type():
    plans = {p.joint: p for p in build_interface_plans(MIXED_URDF)}
    assert set(plans) == {"shoulder", "elbow", "wrist"}  # fixed excluded
    assert plans["shoulder"].command_interfaces == ["position"]
    assert plans["elbow"].command_interfaces == ["position"]
    assert plans["wrist"].command_interfaces == ["velocity"]  # continuous
    assert plans["shoulder"].state_interfaces == ["position", "velocity"]


def test_interface_plans_stable_order():
    plans = build_interface_plans(MIXED_URDF)
    assert [p.joint for p in plans] == ["elbow", "shoulder", "wrist"]


def test_command_override():
    plans = {
        p.joint: p
        for p in build_interface_plans(
            MIXED_URDF, command_overrides={"shoulder": ["effort"]}
        )
    }
    assert plans["shoulder"].command_interfaces == ["effort"]


# -- URDF block generation -----------------------------------------------
def test_generate_ros2_control_xml():
    xml = generate_ros2_control_xml(MIXED_URDF, name="ArmSystem")
    assert 'name="ArmSystem"' in xml
    assert DEFAULT_HARDWARE_PLUGIN in xml
    assert '<joint name="shoulder">' in xml
    assert '<command_interface name="velocity"/>' in xml  # from wrist
    # Fixed joint never appears.
    assert "tool_mount" not in xml


def test_generate_ros2_control_xml_with_hardware_params():
    xml = generate_ros2_control_xml(
        MIXED_URDF, hardware_parameters={"example_param": "5"}
    )
    assert '<param name="example_param">5</param>' in xml


def test_embed_ros2_control_produces_valid_urdf():
    block = generate_ros2_control_xml(MIXED_URDF)
    combined = embed_ros2_control(MIXED_URDF, block)
    root = ET.fromstring(combined)  # must still parse
    assert root.tag == "robot"
    assert root.find("ros2_control") is not None
    # original is untouched
    assert "ros2_control" not in MIXED_URDF


def test_embed_requires_closing_tag():
    try:
        embed_ros2_control("<robot>", "<ros2_control/>")
    except ValueError as exc:
        assert "</robot>" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


# -- controller manager yaml ---------------------------------------------
def test_controller_yaml_revolute_only_is_trajectory():
    cfg = generate_controller_manager_yaml(REVOLUTE_ONLY_URDF)
    cm = cfg["controller_manager"]["ros__parameters"]
    assert cm["update_rate"] == 100
    ctrl = cm["joint_trajectory_controller"]["type"]
    assert "JointTrajectoryController" in ctrl
    block = cfg["joint_trajectory_controller"]["ros__parameters"]
    assert block["joints"] == ["j1", "j2"]
    assert block["command_interfaces"] == ["position"]


def test_controller_yaml_with_continuous_is_velocity():
    cfg = generate_controller_manager_yaml(MIXED_URDF)
    cm = cfg["controller_manager"]["ros__parameters"]
    ctrl = cfg["joint_trajectory_controller"]["ros__parameters"]
    assert ctrl["joints"] == ["elbow", "shoulder", "wrist"]
    # continuous joint forces a velocity controller (no command_interfaces key)
    assert "JointGroupVelocityController" in cm["joint_trajectory_controller"]["type"]
    assert "command_interfaces" not in ctrl


def test_controller_yaml_namespaced():
    cfg = generate_controller_manager_yaml(REVOLUTE_ONLY_URDF, namespace="robot_a")
    assert "robot_a" in cfg
    assert "controller_manager" in cfg["robot_a"]


# -- validation -----------------------------------------------------------
def test_generated_config_validates_clean():
    model = extract_model_summary(MIXED_URDF)
    cfg = generate_controller_manager_yaml(MIXED_URDF)
    report = validate_controllers_config(model, cfg)
    assert report.ok
    assert not report.warnings()  # all movable joints covered


def test_validate_flags_fixed_joint():
    cfg = {
        "controller_manager": {"ros__parameters": {}},
        "jtc": {"ros__parameters": {"joints": ["shoulder", "tool_mount"]}},
    }
    report = validate_controllers_config(MIXED_URDF, cfg)
    assert not report.ok
    assert report.of_code("joint_not_movable")


def test_validate_flags_unknown_joint():
    cfg = {"jtc": {"ros__parameters": {"joints": ["ghost"]}}}
    report = validate_controllers_config(MIXED_URDF, cfg)
    assert report.of_code("joint_not_in_model")


def test_validate_flags_uncontrolled_joint():
    cfg = {"jtc": {"ros__parameters": {"joints": ["shoulder"]}}}
    report = validate_controllers_config(MIXED_URDF, cfg)
    uncontrolled = {i.subject for i in report.of_code("joint_uncontrolled")}
    assert uncontrolled == {"elbow", "wrist"}


def test_validate_flags_double_owned_joint():
    cfg = {
        "a": {"ros__parameters": {"joints": ["shoulder"]}},
        "b": {"ros__parameters": {"joints": ["shoulder"]}},
    }
    report = validate_controllers_config(MIXED_URDF, cfg)
    assert report.of_code("joint_double_owned")


def test_validate_understands_namespaced_config():
    cfg = generate_controller_manager_yaml(REVOLUTE_ONLY_URDF, namespace="robot_a")
    report = validate_controllers_config(REVOLUTE_ONLY_URDF, cfg)
    assert report.ok
