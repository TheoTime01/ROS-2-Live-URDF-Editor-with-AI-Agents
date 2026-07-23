"""Tests for deterministic launch/config drift detection and repair."""

from __future__ import annotations

import os

import pytest

from urdf_live_editor.integration.launch_sync import (
    ChangeKind,
    apply_config_sync,
    check_launch_references,
    extract_model_summary,
    plan_config_sync,
)

SAMPLE_URDF = """
<robot name="sample_arm">
  <link name="base_link"/>
  <link name="link_1"/>
  <link name="link_2"/>
  <link name="link_3"/>
  <link name="tool_link"/>
  <joint name="shoulder" type="revolute">
    <parent link="base_link"/><child link="link_1"/>
    <axis xyz="0 0 1"/><limit lower="-3.14" upper="3.14"/>
  </joint>
  <joint name="elbow" type="revolute">
    <parent link="link_1"/><child link="link_2"/>
    <axis xyz="0 1 0"/><limit lower="-1.57" upper="1.57"/>
  </joint>
  <joint name="wrist" type="continuous">
    <parent link="link_2"/><child link="link_3"/><axis xyz="1 0 0"/>
  </joint>
  <joint name="tool_mount" type="fixed">
    <parent link="link_3"/><child link="tool_link"/>
  </joint>
</robot>
"""


# -- extraction -----------------------------------------------------------
def test_extract_model_summary():
    model = extract_model_summary(SAMPLE_URDF)
    assert model.links == {"base_link", "link_1", "link_2", "link_3", "tool_link"}
    assert set(model.joints) == {"shoulder", "elbow", "wrist", "tool_mount"}
    assert model.root == "base_link"
    assert model.joints["wrist"].type == "continuous"
    assert model.joints["wrist"].is_movable
    assert not model.joints["tool_mount"].is_movable


def test_movable_joints_excludes_fixed():
    model = extract_model_summary(SAMPLE_URDF)
    assert set(model.movable_joints) == {"shoulder", "elbow", "wrist"}
    assert model.joint_names(movable_only=True) == ["elbow", "shoulder", "wrist"]


def test_extract_rejects_malformed_xml():
    with pytest.raises(ValueError, match="well-formed"):
        extract_model_summary("<robot><link name='a'></robot>")


def test_extract_rejects_non_robot_root():
    with pytest.raises(ValueError, match="robot"):
        extract_model_summary("<world><robot/></world>")


# -- planning -------------------------------------------------------------
def test_plan_reports_in_sync_when_matching():
    model = extract_model_summary(SAMPLE_URDF)
    config = {"joints": {"shoulder": {"type": "revolute"},
                         "elbow": {"type": "revolute"},
                         "wrist": {"type": "continuous"}}}
    plan = plan_config_sync(model, config, config_name="validation_policy")
    assert plan.in_sync
    assert "in sync" in plan.summary()


def test_plan_detects_missing_joint():
    model = extract_model_summary(SAMPLE_URDF)
    config = {"joints": {"shoulder": {"type": "revolute"},
                         "elbow": {"type": "revolute"}}}  # wrist missing
    plan = plan_config_sync(model, config)
    adds = plan.of_kind(ChangeKind.ADD)
    assert [a.joint for a in adds] == ["wrist"]
    assert adds[0].new_type == "continuous"


def test_plan_detects_stale_entry():
    model = extract_model_summary(SAMPLE_URDF)
    config = {"joints": {"shoulder": {"type": "revolute"},
                         "elbow": {"type": "revolute"},
                         "wrist": {"type": "continuous"},
                         "ghost": {"type": "revolute"}}}  # not in model
    plan = plan_config_sync(model, config)
    removes = plan.of_kind(ChangeKind.REMOVE)
    assert [a.joint for a in removes] == ["ghost"]


def test_plan_detects_retype():
    model = extract_model_summary(SAMPLE_URDF)
    config = {"joints": {"shoulder": {"type": "revolute"},
                         "elbow": {"type": "revolute"},
                         "wrist": {"type": "revolute"}}}  # should be continuous
    plan = plan_config_sync(model, config)
    retypes = plan.of_kind(ChangeKind.RETYPE)
    assert len(retypes) == 1
    assert retypes[0].joint == "wrist"
    assert retypes[0].old_type == "revolute"
    assert retypes[0].new_type == "continuous"


def test_fixed_joint_in_config_is_flagged_for_removal():
    model = extract_model_summary(SAMPLE_URDF)
    config = {"joints": {"shoulder": {"type": "revolute"},
                         "elbow": {"type": "revolute"},
                         "wrist": {"type": "continuous"},
                         "tool_mount": {"type": "fixed"}}}
    plan = plan_config_sync(model, config)  # movable_only=True by default
    removes = plan.of_kind(ChangeKind.REMOVE)
    assert [a.joint for a in removes] == ["tool_mount"]
    assert "no runtime DOF" in removes[0].detail


def test_plan_accepts_list_style_config():
    model = extract_model_summary(SAMPLE_URDF)
    config = {"joints": ["shoulder", "elbow"]}  # list form, wrist missing
    plan = plan_config_sync(model, config)
    assert [a.joint for a in plan.of_kind(ChangeKind.ADD)] == ["wrist"]


def test_plan_to_dict_is_json_ready():
    model = extract_model_summary(SAMPLE_URDF)
    plan = plan_config_sync(model, {"joints": {}}, config_name="policy")
    data = plan.to_dict()
    assert data["config_name"] == "policy"
    assert data["in_sync"] is False
    assert {a["joint"] for a in data["actions"]} == {"shoulder", "elbow", "wrist"}


# -- applying -------------------------------------------------------------
def test_apply_brings_config_into_sync():
    model = extract_model_summary(SAMPLE_URDF)
    config = {"joints": {"shoulder": {"type": "revolute", "clamp": True},
                         "wrist": {"type": "revolute"},   # wrong type
                         "ghost": {"type": "revolute"}}}  # stale
    plan = plan_config_sync(model, config)
    updated = apply_config_sync(config, model, plan, default_entry={"clamp": True})

    # A second plan on the updated config must be clean.
    assert plan_config_sync(model, updated).in_sync
    # elbow was added with a default block
    assert updated["joints"]["elbow"] == {"clamp": True, "type": "revolute"}
    # wrist retyped but that's the only change to its block
    assert updated["joints"]["wrist"]["type"] == "continuous"
    # shoulder's operator-set key preserved
    assert updated["joints"]["shoulder"]["clamp"] is True
    # ghost removed
    assert "ghost" not in updated["joints"]


def test_apply_does_not_mutate_input():
    model = extract_model_summary(SAMPLE_URDF)
    config = {"joints": {"shoulder": {"type": "revolute"}}}
    plan = plan_config_sync(model, config)
    apply_config_sync(config, model, plan)
    # Original still only has shoulder.
    assert set(config["joints"]) == {"shoulder"}


# -- launch references ----------------------------------------------------
def test_check_launch_references_flags_missing(tmp_path):
    existing = tmp_path / "model.urdf"
    existing.write_text("<robot/>")
    refs = {
        "model": "model.urdf",
        "rviz_config": "missing.rviz",
        "controllers": "",
    }
    issues = check_launch_references(refs, base_dir=str(tmp_path))
    keys = {i.key for i in issues}
    assert "model" not in keys          # exists -> no issue
    assert "rviz_config" in keys        # missing
    assert "controllers" in keys        # empty path


def test_check_launch_references_all_present(tmp_path):
    (tmp_path / "a").write_text("x")
    issues = check_launch_references({"model": "a"}, base_dir=str(tmp_path))
    assert issues == []


def test_check_launch_references_absolute_path(tmp_path):
    f = tmp_path / "abs.urdf"
    f.write_text("<robot/>")
    issues = check_launch_references({"model": str(f)})
    assert issues == []


# -- sample model on disk -------------------------------------------------
def test_sample_arm_urdf_parses():
    here = os.path.dirname(__file__)
    path = os.path.join(here, "..", "..", "..", "models", "sample_arm", "sample_arm.urdf")
    with open(os.path.abspath(path), encoding="utf-8") as handle:
        model = extract_model_summary(handle.read())
    assert model.root == "base_link"
    assert set(model.movable_joints) == {"shoulder", "elbow", "wrist"}
