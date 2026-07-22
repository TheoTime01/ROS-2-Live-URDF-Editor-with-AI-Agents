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
Integration test for the live-editor stack, driven by launch_testing.

Brings up ``live_editor.launch.py`` headless (no RViz) and verifies the
deterministic pipeline end to end at the TF level: the sample arm's moving
links show up on ``/tf``, and commanding a joint through ``/joint_commands``
moves the corresponding transform. This is the automated proof of the
Milestone 2 "editing joints updates the model live" acceptance criterion.
"""

import math
import os
import time
import unittest

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
import launch_testing
import launch_testing.actions
import pytest
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from tf2_msgs.msg import TFMessage

# Moving links of the sample arm; base_link is the (transform-less) root.
MOVING_FRAMES = {'link_1', 'link_2', 'tool_link'}


@pytest.mark.launch_test
def generate_test_description():
    """Launch the full stack (no RViz) and hand control to the tests."""
    pkg_share = get_package_share_directory('urdf_live_editor')
    launch_file = os.path.join(pkg_share, 'launch', 'live_editor.launch.py')
    stack = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(launch_file),
        launch_arguments={'use_rviz': 'false'}.items())
    return LaunchDescription([
        stack,
        launch_testing.actions.ReadyToTest(),
    ])


class _TfListener(Node):
    """Collect the latest transform per child frame from ``/tf``."""

    def __init__(self):
        """Subscribe to ``/tf`` and publish to ``/joint_commands``."""
        super().__init__('tf_listener_test')
        self.transforms = {}
        self.create_subscription(TFMessage, '/tf', self._on_tf, 10)
        self.commands = self.create_publisher(
            JointState, '/joint_commands', 10)

    def _on_tf(self, msg):
        """Record each transform keyed by its child frame."""
        for transform in msg.transforms:
            self.transforms[transform.child_frame_id] = transform

    def command(self, name, position):
        """Publish a single-joint position command."""
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = [name]
        msg.position = [float(position)]
        self.commands.publish(msg)


def _spin_until(node, predicate, timeout=30.0):
    """Spin ``node`` until ``predicate()`` is true or ``timeout`` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        if predicate():
            return True
    return False


class TestLiveEditorTf(unittest.TestCase):
    """Assert the stack produces and updates TF for the sample arm."""

    @classmethod
    def setUpClass(cls):
        """Start rclpy and the shared listener node once for the suite."""
        rclpy.init()
        cls.node = _TfListener()

    @classmethod
    def tearDownClass(cls):
        """Tear down the listener node and rclpy."""
        cls.node.destroy_node()
        rclpy.shutdown()

    def test_moving_frames_are_published(self):
        """Every moving link of the sample arm gets a TF frame."""
        ok = _spin_until(
            self.node,
            lambda: MOVING_FRAMES.issubset(self.node.transforms.keys()))
        missing = MOVING_FRAMES - set(self.node.transforms.keys())
        self.assertTrue(ok, 'missing TF frames after timeout: %s' % missing)

    def test_joint_command_moves_the_transform(self):
        """Commanding the shoulder rotates link_1's transform."""
        self.assertTrue(_spin_until(
            self.node, lambda: 'link_1' in self.node.transforms))
        before = self.node.transforms['link_1'].transform.rotation

        # Drive the shoulder to a clearly non-zero angle; the adapter clamps
        # it to the sample arm's +-1.57 rad limit, so 1.2 rad is safe.
        target = 1.2

        def rotated():
            self.node.command('shoulder', target)
            rot = self.node.transforms['link_1'].transform.rotation
            # shoulder axis is +z, so a rotation shows up as a non-zero qz.
            return abs(rot.z) > 0.1

        self.assertTrue(
            _spin_until(self.node, rotated, timeout=30.0),
            'commanding the shoulder did not move link_1 (before qz=%.3f)'
            % before.z)
        # Sanity: the expected quaternion z for a pure +z rotation of `target`.
        self.assertAlmostEqual(
            self.node.transforms['link_1'].transform.rotation.z,
            math.sin(target / 2.0), delta=0.05)


@launch_testing.post_shutdown_test()
class TestLiveEditorShutdown(unittest.TestCase):
    """Check that the stack shut down without unexpected error codes."""

    def test_clean_shutdown(self, proc_info):
        """No process should exit with an unexpected non-zero code."""
        # 0 = clean, -2 = SIGINT, -15 = SIGTERM: all normal launch teardown.
        launch_testing.asserts.assertExitCodes(
            proc_info, allowable_exit_codes=[0, -2, -15])
