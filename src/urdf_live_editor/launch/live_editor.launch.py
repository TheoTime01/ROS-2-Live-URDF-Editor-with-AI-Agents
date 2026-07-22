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
Bring up the full deterministic live-editor stack.

The pipeline wires four nodes:

* ``urdf_source_node`` expands the Xacro model, latches ``robot_description``
  on a topic, and re-publishes it whenever the file changes.
* ``robot_state_publisher`` turns that description plus ``/joint_states`` into
  TF. It also subscribes to ``robot_description``, so live edits are picked up.
* ``joint_state_adapter_node`` supplies the clamped/wrapped ``/joint_states``.
* ``rviz2`` (optional, off by default) renders the model.

RViz2 is off by default so this launch runs headless under ``launch_testing``
in CI.

Launch arguments:

* ``model_path`` — URDF/Xacro to load (defaults to the bundled sample arm).
* ``use_rviz`` — start RViz2 with the packaged config (default ``false``).
* ``rviz_config`` — override the RViz2 config file.
* ``publish_rate_hz`` — joint-state publish rate for the adapter.
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
    """Return the live-editor launch description."""
    pkg_share = get_package_share_directory('urdf_live_editor')
    default_model = os.path.join(pkg_share, 'models', 'sample_arm',
                                 'sample_arm.urdf.xacro')
    default_rviz = PathJoinSubstitution(
        [FindPackageShare('urdf_live_editor'), 'rviz', 'live_editor.rviz'])

    model_path = LaunchConfiguration('model_path')
    use_rviz = LaunchConfiguration('use_rviz')
    rviz_config = LaunchConfiguration('rviz_config')
    publish_rate_hz = LaunchConfiguration('publish_rate_hz')

    declare_args = [
        DeclareLaunchArgument(
            'model_path', default_value=default_model,
            description='URDF/Xacro model file to load and hot-reload.'),
        DeclareLaunchArgument(
            'use_rviz', default_value='false',
            description='Start RViz2 with the packaged config.'),
        DeclareLaunchArgument(
            'rviz_config', default_value=default_rviz,
            description='RViz2 config file to open when use_rviz is true.'),
        DeclareLaunchArgument(
            'publish_rate_hz', default_value='30.0',
            description='Rate at which the adapter publishes /joint_states.'),
    ]

    # robot_state_publisher needs an initial description to build its TF tree
    # before the first topic message; expand the Xacro at launch time. It also
    # subscribes to the robot_description topic, so live edits from
    # urdf_source_node are picked up automatically.
    robot_description = ParameterValue(
        Command(['xacro ', model_path]), value_type=str)

    source_node = Node(
        package='urdf_live_editor',
        executable='urdf_source_node',
        name='urdf_source_node',
        output='screen',
        parameters=[{'model_path': model_path}],
    )

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}],
    )

    joint_state_adapter = Node(
        package='urdf_live_editor',
        executable='joint_state_adapter_node',
        name='joint_state_adapter_node',
        output='screen',
        # LaunchConfiguration is a string; coerce so the double-typed
        # publish_rate_hz parameter does not hit a type mismatch.
        parameters=[{'publish_rate_hz': ParameterValue(
            publish_rate_hz, value_type=float)}],
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
        source_node,
        robot_state_publisher,
        joint_state_adapter,
        rviz_node,
    ])
