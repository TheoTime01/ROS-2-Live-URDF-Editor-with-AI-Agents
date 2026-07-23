"""Tests for collision-geometry and inertial validation."""

from __future__ import annotations

import os

import pytest

from urdf_live_editor.extensions.physical_validation import (
    is_positive_definite_3x3,
    symmetric_eigenvalues_3x3,
    validate_physical,
)

GOOD_LINK = """
<robot name="r">
  <link name="base_link">
    <inertial>
      <mass value="1.0"/>
      <origin xyz="0 0 0"/>
      <inertia ixx="0.01" ixy="0" ixz="0" iyy="0.01" iyz="0" izz="0.01"/>
    </inertial>
    <collision><geometry><box size="0.1 0.1 0.1"/></geometry></collision>
  </link>
  <link name="tip">
    <inertial>
      <mass value="0.5"/>
      <origin xyz="0 0 0"/>
      <inertia ixx="0.001" ixy="0" ixz="0" iyy="0.001" iyz="0" izz="0.001"/>
    </inertial>
    <collision><geometry><sphere radius="0.02"/></geometry></collision>
  </link>
  <joint name="j" type="revolute">
    <parent link="base_link"/><child link="tip"/>
  </joint>
</robot>
"""


# -- linear algebra helpers ----------------------------------------------
def test_eigenvalues_diagonal():
    vals = symmetric_eigenvalues_3x3([[2, 0, 0], [0, 3, 0], [0, 0, 4]])
    assert [round(v, 9) for v in vals] == [2.0, 3.0, 4.0]


def test_eigenvalues_non_diagonal():
    # [[2,1,0],[1,2,0],[0,0,3]] has eigenvalues 1, 3, 3.
    vals = symmetric_eigenvalues_3x3([[2, 1, 0], [1, 2, 0], [0, 0, 3]])
    assert [round(v, 6) for v in vals] == [1.0, 3.0, 3.0]


def test_positive_definite():
    assert is_positive_definite_3x3([[2, 0, 0], [0, 3, 0], [0, 0, 4]])
    assert not is_positive_definite_3x3([[-1, 0, 0], [0, 1, 0], [0, 0, 1]])
    assert not is_positive_definite_3x3([[1, 2, 0], [2, 1, 0], [0, 0, 1]])


# -- validation ----------------------------------------------------------
def test_good_model_passes():
    report = validate_physical(GOOD_LINK)
    assert report.ok
    assert not report.errors()


def test_nonpositive_mass_is_error():
    urdf = """
    <robot name="r">
      <link name="a">
        <inertial><mass value="0"/>
          <inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/>
        </inertial>
      </link>
    </robot>
    """
    report = validate_physical(urdf)
    assert not report.ok
    assert report.of_code("mass_nonpositive")


def test_missing_mass_value_is_error():
    urdf = """
    <robot name="r">
      <link name="a">
        <inertial><mass/>
          <inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/>
        </inertial>
      </link>
    </robot>
    """
    report = validate_physical(urdf)
    assert report.of_code("mass_missing")


def test_non_spd_inertia_is_error():
    urdf = """
    <robot name="r">
      <link name="a">
        <inertial><mass value="1"/>
          <inertia ixx="-1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/>
        </inertial>
      </link>
    </robot>
    """
    report = validate_physical(urdf)
    assert report.of_code("inertia_not_spd")


def test_triangle_inequality_is_warning_not_error():
    # ixx=1, iyy=1, izz=3 -> SPD but 1+1 < 3, implausible mass distribution.
    urdf = """
    <robot name="r">
      <link name="a">
        <inertial><mass value="1"/>
          <inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="3"/>
        </inertial>
      </link>
    </robot>
    """
    report = validate_physical(urdf)
    assert report.ok  # only a warning
    assert report.of_code("inertia_triangle_inequality")


def test_zero_inertia_tensor_is_error():
    urdf = """
    <robot name="r">
      <link name="a">
        <inertial><mass value="1"/>
          <inertia ixx="0" ixy="0" ixz="0" iyy="0" iyz="0" izz="0"/>
        </inertial>
      </link>
    </robot>
    """
    report = validate_physical(urdf)
    assert report.of_code("inertia_zero")


def test_missing_inertial_on_child_link_is_warning():
    urdf = """
    <robot name="r">
      <link name="base"/>
      <link name="child"/>
      <joint name="j" type="fixed">
        <parent link="base"/><child link="child"/>
      </joint>
    </robot>
    """
    report = validate_physical(urdf)
    missing = report.of_code("inertial_missing")
    subjects = {i.subject for i in missing}
    assert "child" in subjects  # child of a joint -> warning
    assert report.ok            # warnings only


def test_negative_geometry_dimension_is_error():
    urdf = """
    <robot name="r">
      <link name="a">
        <inertial><mass value="1"/>
          <inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/>
        </inertial>
        <collision><geometry><cylinder radius="-0.1" length="0.2"/></geometry></collision>
      </link>
    </robot>
    """
    report = validate_physical(urdf)
    assert report.of_code("geometry_nonpositive")


def test_require_collision_promotes_missing_collision_to_error():
    urdf = """
    <robot name="r">
      <link name="a">
        <inertial><mass value="1"/>
          <inertia ixx="1" ixy="0" ixz="0" iyy="1" iyz="0" izz="1"/>
        </inertial>
      </link>
    </robot>
    """
    lenient = validate_physical(urdf, require_collision=False)
    assert lenient.ok  # only info
    strict = validate_physical(urdf, require_collision=True)
    assert not strict.ok
    assert strict.of_code("collision_missing")


def test_rejects_malformed_xml():
    with pytest.raises(ValueError, match="well-formed"):
        validate_physical("<robot><link></robot>")


def test_rejects_non_robot_root():
    with pytest.raises(ValueError, match="robot"):
        validate_physical("<world/>")


def test_sim_sample_model_passes():
    here = os.path.dirname(__file__)
    path = os.path.join(
        here, "..", "..", "..", "models", "sample_arm", "sample_arm_sim.urdf"
    )
    with open(os.path.abspath(path), encoding="utf-8") as handle:
        report = validate_physical(handle.read(), require_collision=True)
    assert report.ok, report.summary()
    assert not report.errors()
