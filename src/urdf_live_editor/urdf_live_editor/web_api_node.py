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
Expose the edit pipeline over HTTP/WebSocket (Milestone 3).

``web_api_node`` is the network front end onto the deterministic core. The
request routing, validation, versioning, and event streaming all live in
transport-agnostic, offline-tested modules under
:mod:`urdf_live_editor.web`; this ``main`` only wires them into ROS.

At start-up the node seeds a :class:`WebApiService` from either a ``model_path``
parameter (loading/expanding the file) or the first valid ``robot_description``
message it sees, then serves the REST + WebSocket API. Every edit applied or
rolled back through the API is republished on the latched ``robot_description``
topic, so an API-driven change flows straight to ``robot_state_publisher`` and
the joint-state adapter and shows up live in RViz2 — the same edit flow that is
available on the ROS side, now drivable over the wire.
"""


def main(args=None):
    """Start the web API node: seed the service, serve, republish edits."""
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSDurabilityPolicy, QoSProfile
    from std_msgs.msg import String

    from urdf_live_editor.urdf_source_node import UrdfSource
    from urdf_live_editor.web.server import WebApiServer
    from urdf_live_editor.web.service import WebApiService

    rclpy.init(args=args)
    node = Node('web_api_node')
    host = node.declare_parameter('host', '127.0.0.1').value
    port = node.declare_parameter('port', 8080).value
    model_path = node.declare_parameter('model_path', '').value

    latched = QoSProfile(depth=1)
    latched.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL
    description_pub = node.create_publisher(String, 'robot_description', latched)

    state = {'server': None}

    def republish(urdf):
        """Push an API-driven model change onto robot_description."""
        description_pub.publish(String(data=urdf))

    def start_service(urdf, source):
        """Seed the service from ``urdf`` and start the HTTP server once."""
        if state['server'] is not None:
            return
        try:
            service = WebApiService.from_urdf(urdf, on_commit=republish)
        except ValueError as exc:
            node.get_logger().warn(
                'cannot seed web API from %s: %s' % (source, exc))
            return
        server = WebApiServer(service, host=host, port=int(port)).start()
        state['server'] = server
        republish(service.coordinator.current_urdf())
        node.get_logger().info(
            'web_api_node serving REST + WebSocket on http://%s:%d '
            '(seeded from %s).' % (server.host, server.port, source))

    if model_path:
        start_service(UrdfSource(model_path).load(), model_path)
    else:
        node.get_logger().info(
            'web_api_node waiting for robot_description to seed the API.')

    def on_description(msg):
        """Seed the service from the first valid robot_description seen."""
        start_service(msg.data, 'robot_description')

    node.create_subscription(
        String, 'robot_description', on_description, latched)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if state['server'] is not None:
            state['server'].stop()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
