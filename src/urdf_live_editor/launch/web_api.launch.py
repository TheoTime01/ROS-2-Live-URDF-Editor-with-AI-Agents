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
Bring up the edit pipeline behind the HTTP/WebSocket API.

This launch makes the deterministic core reachable over the network and keeps
the visualization in sync with API-driven edits:

* ``web_api_node`` seeds itself from the model, serves the REST + WebSocket API,
  and republishes ``robot_description`` on the latched topic whenever an edit is
  applied or rolled back through the API.
* ``robot_state_publisher`` turns that description into TF and subscribes to the
  topic, so an edit made over HTTP updates the TF tree live.
* ``rviz2`` (optional, off by default) renders the model.

Launch arguments:

* ``model_path`` — URDF/Xacro to load (defaults to the bundled sample arm).
* ``host`` / ``port`` — address the API binds to (default ``127.0.0.1:8080``).
* ``use_rviz`` — start RViz2 with the packaged config (default ``false``).
* ``rviz_config`` — override the RViz2 config file.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import (
    Command, LaunchConfiguration, PathJoinSubstitution)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Return the web-API launch description."""
    pkg_share = get_package_share_directory('urdf_live_editor')
    default_model = os.path.join(pkg_share, 'models', 'sample_arm',
                                 'sample_arm.urdf.xacro')
    default_rviz = PathJoinSubstitution(
        [FindPackageShare('urdf_live_editor'), 'rviz', 'live_editor.rviz'])

    model_path = LaunchConfiguration('model_path')
    host = LaunchConfiguration('host')
    port = LaunchConfiguration('port')
    use_rviz = LaunchConfiguration('use_rviz')
    rviz_config = LaunchConfiguration('rviz_config')

    declare_args = [
        DeclareLaunchArgument(
            'model_path', default_value=default_model,
            description='URDF/Xacro model file to seed the API with.'),
        DeclareLaunchArgument(
            'host', default_value='127.0.0.1',
            description='Address the HTTP/WebSocket API binds to.'),
        DeclareLaunchArgument(
            'port', default_value='8080',
            description='TCP port the HTTP/WebSocket API listens on.'),
        DeclareLaunchArgument(
            'use_rviz', default_value='false',
            description='Start RViz2 with the packaged config.'),
        DeclareLaunchArgument(
            'rviz_config', default_value=default_rviz,
            description='RViz2 config file to open when use_rviz is true.'),
    ]

    # robot_state_publisher needs an initial description to build its TF tree
    # before the first topic message; expand the Xacro at launch time. It also
    # subscribes to robot_description, so edits the API republishes are picked
    # up automatically.
    robot_description = ParameterValue(
        Command(['xacro ', model_path]), value_type=str)

    web_api_node = Node(
        package='urdf_live_editor',
        executable='web_api_node',
        name='web_api_node',
        output='screen',
        parameters=[{
            'model_path': model_path,
            'host': host,
            'port': ParameterValue(port, value_type=int),
        }],
    )

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}],
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', rviz_config],
        condition=IfCondition(use_rviz),
    )

    return LaunchDescription(declare_args + [
        web_api_node,
        robot_state_publisher,
        rviz_node,
    ])
