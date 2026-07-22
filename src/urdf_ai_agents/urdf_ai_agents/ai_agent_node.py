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
ROS 2 node hosting the Claude Agent SDK layer.

The node builds the deterministic tool runtime -- a
:class:`~urdf_ai_agents.tools.toolbox.UrdfToolbox` over the trusted edit
pipeline, wrapped by a :class:`~urdf_ai_agents.dispatch.ToolDispatcher` with the
mutation guard and audit trail -- and drives it either from a recorded scenario
file (deterministic, no API) or against live Claude through the SDK. Republishing
``robot_description`` on every applied edit is delegated to the same
``on_commit`` hook the web API uses, so an AI edit updates RViz2 live too.

The offline, ROS-free helpers (:func:`load_urdf`, :func:`build_dispatcher`,
:func:`run_recorded`) carry the logic and are unit-tested directly; ``main``
only binds them to a running node.
"""

import json

from urdf_ai_agents.dispatch import ToolDispatcher
from urdf_ai_agents.session import AgentSession, RecordedPlanner
from urdf_ai_agents.tools.toolbox import UrdfToolbox


def load_urdf(model_path=None, robot_description=None):
    """Return URDF text from ``robot_description`` or a ``model_path`` file."""
    if robot_description:
        return robot_description
    if model_path:
        with open(model_path, 'r', encoding='utf-8') as handle:
            return handle.read()
    raise ValueError('provide either robot_description or model_path')


def build_dispatcher(urdf, require_valid=True, on_commit=None):
    """Build a :class:`ToolDispatcher` over ``urdf`` (offline, no ROS)."""
    toolbox = UrdfToolbox.from_urdf(
        urdf, require_valid=require_valid, on_commit=on_commit)
    return ToolDispatcher(toolbox)


def run_recorded(urdf, scenario_file, instruction, require_valid=True):
    """Run one instruction from a recorded scenario file, no API involved."""
    with open(scenario_file, 'r', encoding='utf-8') as handle:
        planner = RecordedPlanner.from_dict(json.load(handle))
    dispatcher = build_dispatcher(urdf, require_valid=require_valid)
    session = AgentSession(dispatcher, planner)
    return session.run(instruction)


def main(args=None):
    """Start the AI agent node and spin until shutdown."""
    import rclpy
    from rclpy.node import Node

    rclpy.init(args=args)
    node = Node('ai_agent_node')
    node.declare_parameter('model_path', '')
    node.declare_parameter('robot_description', '')
    node.declare_parameter('scenario_file', '')
    node.declare_parameter('instruction', '')

    logger = node.get_logger()
    logger.info('ai_agent_node started; Claude Agent SDK layer ready.')

    model_path = node.get_parameter('model_path').value
    robot_description = node.get_parameter('robot_description').value
    scenario_file = node.get_parameter('scenario_file').value
    instruction = node.get_parameter('instruction').value

    try:
        if scenario_file and instruction and (model_path or robot_description):
            urdf = load_urdf(model_path, robot_description)
            result = run_recorded(urdf, scenario_file, instruction)
            logger.info(
                "recorded run for %r: applied=%s, %d tool call(s)"
                % (instruction, result.applied, len(result.transcript)))
        else:
            logger.info(
                'no recorded scenario configured; set model_path/'
                'robot_description, scenario_file, and instruction to run one.')
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
