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
Integration test for ``web_api_node``, driven by launch_testing.

Launches the web API node against the bundled sample arm and drives the edit
flow over real HTTP, then checks that an API-applied edit is republished on the
latched ``robot_description`` topic. That closes the Milestone 3 loop: the same
stage -> validate -> apply pipeline available on the ROS side is drivable
through the API, and an API edit flows straight back onto the ROS graph.
"""

import http.client
import json
import os
import time
import unittest

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import launch_testing
import launch_testing.actions
import pytest
import rclpy
from rclpy.node import Node as RclpyNode
from rclpy.qos import QoSDurabilityPolicy, QoSProfile
from std_msgs.msg import String

API_HOST = '127.0.0.1'
API_PORT = 8137


@pytest.mark.launch_test
def generate_test_description():
    """Launch web_api_node seeded from the sample arm and start testing."""
    pkg_share = get_package_share_directory('urdf_live_editor')
    model_path = os.path.join(
        pkg_share, 'models', 'sample_arm', 'sample_arm.urdf.xacro')
    web_api = Node(
        package='urdf_live_editor',
        executable='web_api_node',
        name='web_api_node',
        output='screen',
        parameters=[{
            'model_path': model_path,
            'host': API_HOST,
            'port': API_PORT,
        }],
    )
    return LaunchDescription([
        web_api,
        launch_testing.actions.ReadyToTest(),
    ])


def _http(method, path, body=None, timeout=5.0):
    """Perform one REST call to the node, returning ``(status, json)``."""
    conn = http.client.HTTPConnection(API_HOST, API_PORT, timeout=timeout)
    try:
        payload = json.dumps(body) if body is not None else None
        headers = {'Content-Type': 'application/json'} if payload else {}
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = response.read().decode('utf-8')
        return response.status, json.loads(data)
    finally:
        conn.close()


def _http_with_retry(method, path, body=None, deadline=30.0):
    """Retry a REST call until the server accepts connections or time out."""
    end = time.time() + deadline
    last = None
    while time.time() < end:
        try:
            return _http(method, path, body)
        except (ConnectionError, OSError) as exc:
            last = exc
            time.sleep(0.2)
    raise AssertionError('web API never became reachable: %s' % last)


class _DescriptionListener(RclpyNode):
    """Latch onto ``robot_description`` and keep the most recent value."""

    def __init__(self):
        """Subscribe to the latched robot_description topic."""
        super().__init__('web_api_description_listener')
        self.latest = None
        latched = QoSProfile(depth=1)
        latched.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL
        self.create_subscription(
            String, 'robot_description', self._on_description, latched)

    def _on_description(self, msg):
        """Record the latest robot_description payload."""
        self.latest = msg.data


def _spin_until(node, predicate, timeout=30.0):
    """Spin ``node`` until ``predicate()`` holds or ``timeout`` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        if predicate():
            return True
    return False


class TestWebApiIntegration(unittest.TestCase):
    """Drive the edit flow over HTTP and watch the ROS graph react."""

    @classmethod
    def setUpClass(cls):
        """Start rclpy and a shared robot_description listener."""
        rclpy.init()
        cls.node = _DescriptionListener()

    @classmethod
    def tearDownClass(cls):
        """Tear down the listener node and rclpy."""
        cls.node.destroy_node()
        rclpy.shutdown()

    def test_rest_serves_the_seeded_model(self):
        """GET /model returns the sample arm seeded from disk."""
        # The two tests share one node/process and unittest runs them
        # alphabetically, so an edit may already have been applied. Assert on
        # the seeded content, which survives later additive edits, rather than
        # on a specific version index.
        status, body = _http_with_retry('GET', '/model')
        self.assertEqual(status, 200)
        self.assertIn('base_link', body['urdf'])
        self.assertIn('shoulder', body['urdf'])
        self.assertTrue(body['validation']['is_valid'])

    def test_api_edit_is_republished_on_the_ros_topic(self):
        """An edit applied over HTTP shows up on robot_description."""
        # Make sure the server is up first.
        _http_with_retry('GET', '/health')
        operations = [
            {'op': 'add_link', 'name': 'probe'},
            {'op': 'add_joint', 'name': 'probe_joint', 'joint_type': 'fixed',
             'parent': 'tool_link', 'child': 'probe'},
        ]
        status, body = _http('POST', '/apply', {'operations': operations})
        self.assertEqual(status, 200)
        self.assertTrue(body['applied'])
        self.assertIn('probe', body['diff']['added_links'])

        # The applied edit must reach the latched robot_description topic.
        self.assertTrue(
            _spin_until(
                self.node,
                lambda: self.node.latest is not None
                and 'probe_joint' in self.node.latest),
            'API edit was not republished on robot_description')


@launch_testing.post_shutdown_test()
class TestWebApiShutdown(unittest.TestCase):
    """Check that the node shut down without unexpected error codes."""

    def test_clean_shutdown(self, proc_info):
        """No process should exit with an unexpected non-zero code."""
        # 0 = clean, -2 = SIGINT, -15 = SIGTERM: all normal launch teardown.
        launch_testing.asserts.assertExitCodes(
            proc_info, allowable_exit_codes=[0, -2, -15])
