"""Tests for Gazebo simulation artifact generation and readiness checks."""

from __future__ import annotations

import os

from urdf_live_editor.extensions.gazebo import (
    build_spawn_plan,
    check_gazebo_readiness,
    generate_gazebo_ros2_control_block,
)


def _sim_urdf() -> str:
    here = os.path.dirname(__file__)
    path = os.path.join(
        here, "..", "..", "..", "models", "sample_arm", "sample_arm_sim.urdf"
    )
    with open(os.path.abspath(path), encoding="utf-8") as handle:
        return handle.read()


# -- plugin block ---------------------------------------------------------
def test_gazebo_control_block_plain_path():
    block = generate_gazebo_ros2_control_block(controllers_path="config/ctrl.yaml")
    assert "libgazebo_ros2_control.so" in block
    assert "<parameters>config/ctrl.yaml</parameters>" in block


def test_gazebo_control_block_package_relative():
    block = generate_gazebo_ros2_control_block(
        controllers_path="config/ctrl.yaml", parameters_package="my_pkg"
    )
    assert "$(find my_pkg)/config/ctrl.yaml" in block


# -- spawn plan -----------------------------------------------------------
def test_spawn_plan_ordering():
    plan = build_spawn_plan(entity_name="arm", controllers=["arm_controller"])
    kinds = [s.kind for s in plan.steps]
    # gazebo, then RSP before spawn, then spawners
    assert kinds[:3] == ["gazebo", "robot_state_publisher", "spawn_entity"]
    assert kinds[3:] == ["spawner", "spawner"]
    # orders are strictly increasing
    orders = [s.order for s in plan.steps]
    assert orders == sorted(orders)
    assert orders == list(range(1, len(orders) + 1))


def test_spawn_plan_broadcaster_first():
    plan = build_spawn_plan(entity_name="arm", controllers=["arm_controller"])
    spawners = [s.detail["controller"] for s in plan.steps if s.kind == "spawner"]
    assert spawners[0] == "joint_state_broadcaster"
    assert "arm_controller" in spawners


def test_spawn_plan_dedupes_broadcaster():
    plan = build_spawn_plan(
        entity_name="arm", controllers=["joint_state_broadcaster", "arm_controller"]
    )
    spawners = [s.detail["controller"] for s in plan.steps if s.kind == "spawner"]
    assert spawners.count("joint_state_broadcaster") == 1


def test_spawn_plan_namespaced():
    plan = build_spawn_plan(entity_name="arm", namespace="robot_a")
    rsp = next(s for s in plan.steps if s.kind == "robot_state_publisher")
    assert rsp.detail["namespace"] == "/robot_a"


def test_spawn_plan_to_dict():
    plan = build_spawn_plan(entity_name="arm")
    data = plan.to_dict()
    assert data["entity_name"] == "arm"
    assert data["steps"][0]["order"] == 1


# -- readiness ------------------------------------------------------------
def test_sim_model_is_gazebo_ready():
    report = check_gazebo_readiness(_sim_urdf())
    assert report.ok, report.summary()


def test_massless_child_link_blocks_gazebo():
    urdf = """
    <robot name="r">
      <link name="base">
        <inertial><mass value="1"/>
          <inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/>
        </inertial>
        <collision><geometry><box size="0.1 0.1 0.1"/></geometry></collision>
      </link>
      <link name="floaty"/>
      <joint name="j" type="revolute">
        <parent link="base"/><child link="floaty"/>
        <axis xyz="0 0 1"/><limit lower="-1" upper="1"/>
      </joint>
    </robot>
    """
    report = check_gazebo_readiness(urdf)
    assert not report.ok
    assert report.of_code("gazebo_inertial_missing")


def test_missing_collision_is_gazebo_warning():
    urdf = """
    <robot name="r">
      <link name="base">
        <inertial><mass value="1"/>
          <inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/>
        </inertial>
      </link>
    </robot>
    """
    report = check_gazebo_readiness(urdf)
    assert report.ok  # only a warning
    assert report.of_code("gazebo_collision_missing")
