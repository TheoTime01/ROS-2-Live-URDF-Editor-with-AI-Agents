"""Tests for multi-robot / multi-model session management."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from urdf_live_editor.extensions.sessions import (
    DuplicateSessionError,
    ModelSession,
    SessionRegistry,
    is_valid_namespace,
    namespace_urdf,
)

TWO_LINK = """
<robot name="r">
  <link name="base_link"/>
  <link name="tip"/>
  <joint name="j" type="revolute">
    <parent link="base_link"/><child link="tip"/>
    <axis xyz="0 0 1"/><limit lower="-1" upper="1"/>
  </joint>
</robot>
"""


# -- namespace validation -------------------------------------------------
def test_valid_namespace():
    assert is_valid_namespace("robot_a")
    assert is_valid_namespace("_hidden")
    assert not is_valid_namespace("1robot")
    assert not is_valid_namespace("robot/a")
    assert not is_valid_namespace("")


# -- URDF namespacing -----------------------------------------------------
def test_namespace_urdf_prefixes_names_and_refs():
    out = namespace_urdf(TWO_LINK, "arm1")
    root = ET.fromstring(out)
    links = {link.get("name") for link in root.findall("link")}
    assert links == {"arm1_base_link", "arm1_tip"}
    joint = root.find("joint")
    assert joint.get("name") == "arm1_j"
    assert joint.find("parent").get("link") == "arm1_base_link"
    assert joint.find("child").get("link") == "arm1_tip"


def test_namespace_urdf_custom_separator():
    out = namespace_urdf(TWO_LINK, "arm1", separator="/")
    assert 'name="arm1/base_link"' in out


def test_namespace_urdf_rewrites_mimic():
    urdf = """
    <robot name="r">
      <link name="a"/><link name="b"/><link name="c"/>
      <joint name="lead" type="revolute">
        <parent link="a"/><child link="b"/>
        <axis xyz="0 0 1"/><limit lower="-1" upper="1"/>
      </joint>
      <joint name="follow" type="revolute">
        <parent link="b"/><child link="c"/>
        <axis xyz="0 0 1"/><limit lower="-1" upper="1"/>
        <mimic joint="lead" multiplier="1.0"/>
      </joint>
    </robot>
    """
    out = namespace_urdf(urdf, "g")
    root = ET.fromstring(out)
    mimic = root.find(".//mimic")
    assert mimic.get("joint") == "g_lead"


def test_namespace_urdf_rejects_bad_prefix():
    with pytest.raises(ValueError, match="invalid namespace"):
        namespace_urdf(TWO_LINK, "1bad")


def test_namespace_urdf_rejects_malformed():
    with pytest.raises(ValueError, match="well-formed"):
        namespace_urdf("<robot><link></robot>", "ns")


# -- ModelSession ---------------------------------------------------------
def test_session_default_frame_prefix():
    s = ModelSession(session_id="s1", namespace="arm1", urdf=TWO_LINK)
    assert s.effective_frame_prefix == "arm1_"
    assert set(s.summary().links) == {"base_link", "tip"}


def test_session_namespaced_urdf():
    s = ModelSession(session_id="s1", namespace="arm1", urdf=TWO_LINK)
    out = s.namespaced_urdf()
    assert "arm1_base_link" in out


def test_session_rejects_bad_namespace():
    with pytest.raises(ValueError, match="invalid namespace"):
        ModelSession(session_id="s1", namespace="bad ns", urdf=TWO_LINK)


# -- registry -------------------------------------------------------------
def test_registry_add_and_get():
    reg = SessionRegistry()
    reg.add(ModelSession("s1", "arm1", TWO_LINK))
    reg.add(ModelSession("s2", "arm2", TWO_LINK))
    assert len(reg) == 2
    assert "s1" in reg
    assert reg.get("s2").namespace == "arm2"
    assert [s.session_id for s in reg.list()] == ["s1", "s2"]


def test_registry_rejects_duplicate_id():
    reg = SessionRegistry()
    reg.add(ModelSession("s1", "arm1", TWO_LINK))
    with pytest.raises(DuplicateSessionError, match="session id"):
        reg.add(ModelSession("s1", "arm2", TWO_LINK))


def test_registry_rejects_duplicate_namespace():
    reg = SessionRegistry()
    reg.add(ModelSession("s1", "arm1", TWO_LINK))
    with pytest.raises(DuplicateSessionError, match="namespace"):
        reg.add(ModelSession("s2", "arm1", TWO_LINK))


def test_registry_remove_frees_namespace():
    reg = SessionRegistry()
    reg.add(ModelSession("s1", "arm1", TWO_LINK))
    reg.remove("s1")
    assert len(reg) == 0
    reg.add(ModelSession("s2", "arm1", TWO_LINK))  # namespace reusable now
    assert len(reg) == 1


def test_combined_frames_and_scene_ok():
    reg = SessionRegistry()
    reg.add(ModelSession("s1", "arm1", TWO_LINK))
    reg.add(ModelSession("s2", "arm2", TWO_LINK))
    frames = reg.combined_frames()
    assert frames == [
        "arm1_base_link",
        "arm1_tip",
        "arm2_base_link",
        "arm2_tip",
    ]
    report = reg.check_scene()
    assert report.ok
    assert report.of_code("scene_ok")


def test_scene_detects_frame_collision_from_custom_prefix():
    reg = SessionRegistry()
    reg.add(ModelSession("s1", "arm1", TWO_LINK, frame_prefix="r_"))
    reg.add(ModelSession("s2", "arm2", TWO_LINK, frame_prefix="r_"))
    report = reg.check_scene()
    assert not report.ok
    assert report.of_code("frame_collision")


def test_registry_to_dict():
    reg = SessionRegistry()
    reg.add(ModelSession("s1", "arm1", TWO_LINK, name="Left arm"))
    data = reg.to_dict()
    assert data["count"] == 1
    assert data["sessions"][0]["name"] == "Left arm"
    assert "arm1_tip" in data["frames"]
