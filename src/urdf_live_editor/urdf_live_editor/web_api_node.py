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

"""Node that exposes REST/WebSocket endpoints for the edit pipeline.

Milestone 0 skeleton: the node starts, logs, and spins. The HTTP and
WebSocket surface is implemented in Milestone 3.
"""


def main(args=None):
    """Start the web API node and spin until shutdown."""
    import rclpy
    from rclpy.node import Node

    rclpy.init(args=args)
    node = Node('web_api_node')
    node.get_logger().info('web_api_node started (Milestone 0 skeleton).')
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
