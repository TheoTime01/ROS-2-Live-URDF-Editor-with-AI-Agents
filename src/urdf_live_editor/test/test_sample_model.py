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

"""Parse the sample robot model to lock in the offline test harness."""

import os
import xml.etree.ElementTree as ET

import pytest


def _find_sample_model():
    """Return the path to the sample arm model, searching parent dirs."""
    path = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidate = os.path.join(
            path, 'models', 'sample_arm', 'sample_arm.urdf.xacro')
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    pytest.skip('sample_arm.urdf.xacro not found in any parent directory')


def test_sample_model_is_well_formed():
    """The sample URDF/Xacro is well-formed XML rooted at <robot>."""
    root = ET.parse(_find_sample_model()).getroot()
    assert root.tag == 'robot'
    assert root.get('name') == 'sample_arm'


def test_sample_model_has_links_and_joints():
    """The sample model declares links and joints of the expected types."""
    root = ET.parse(_find_sample_model()).getroot()
    links = {link.get('name') for link in root.findall('link')}
    joints = {joint.get('name'): joint.get('type')
              for joint in root.findall('joint')}
    assert {'base_link', 'link_1', 'link_2', 'tool_link'} <= links
    assert joints['shoulder'] == 'revolute'
    assert joints['elbow'] == 'revolute'
    assert joints['wrist'] == 'continuous'


def test_sample_model_joints_reference_existing_links():
    """Every joint parent/child refers to a declared link."""
    root = ET.parse(_find_sample_model()).getroot()
    links = {link.get('name') for link in root.findall('link')}
    for joint in root.findall('joint'):
        parent = joint.find('parent').get('link')
        child = joint.find('child').get('link')
        assert parent in links
        assert child in links
