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
Maintain runtime joint values and publish ``/joint_states``.

:class:`JointStateAdapter` is the deterministic, offline-testable core of this
node. It tracks a position for every *actuated* joint of a
:class:`~urdf_live_editor.model.robot_model.RobotModel` and enforces the
per-type kinematic envelope on every command it receives: a ``revolute`` or
``prismatic`` joint is clamped to its ``[lower, upper]`` limit, and a
``continuous`` joint is wrapped into ``(-pi, pi]`` so an unbounded spinner never
grows without bound. ``fixed`` joints expose no degree of freedom and are
ignored. When the model is replaced (a live edit), positions of joints that
survive are carried over and re-normalized, new joints start at zero, and
removed joints are dropped.

``main`` wraps the adapter in a ROS 2 node: it latches onto ``robot_description``
to rebuild the joint set on every edit, accepts commands on ``joint_commands``,
and publishes ``sensor_msgs/JointState`` on ``joint_states`` at a fixed rate so
``robot_state_publisher`` can turn them into live TF.
"""

import math

#: Joint types that carry a single controllable degree of freedom and therefore
#: appear in ``/joint_states``. ``fixed``/``floating``/``planar`` are excluded.
ACTUATED_TYPES = frozenset(('revolute', 'continuous', 'prismatic'))

_TWO_PI = 2.0 * math.pi


def wrap_angle(value):
    """Wrap ``value`` (radians) into the half-open range ``(-pi, pi]``."""
    if not math.isfinite(value):
        return 0.0
    wrapped = math.fmod(value, _TWO_PI)
    if wrapped <= -math.pi:
        wrapped += _TWO_PI
    elif wrapped > math.pi:
        wrapped -= _TWO_PI
    return wrapped


def clamp(value, lower, upper):
    """Clamp ``value`` to ``[lower, upper]``; open bounds are ignored."""
    if not math.isfinite(value):
        return lower if lower is not None else (
            upper if upper is not None else 0.0)
    if lower is not None and value < lower:
        return lower
    if upper is not None and value > upper:
        return upper
    return value


class JointStateAdapter:
    """Track and normalize joint positions for the actuated joints of a model."""

    def __init__(self, model=None):
        """Start empty, or seeded from ``model`` when one is given."""
        self._joints = {}
        self._positions = {}
        if model is not None:
            self.set_model(model)

    def set_model(self, model):
        """
        Rebuild the actuated-joint set from ``model``.

        Positions of joints that still exist are preserved (re-normalized to
        the possibly-changed limits); joints that disappeared are dropped and
        newly added joints start at a normalized zero.
        """
        previous = self._positions
        self._joints = {
            name: joint for name, joint in model.joints.items()
            if joint.joint_type in ACTUATED_TYPES}
        self._positions = {
            name: self._normalize(joint, previous.get(name, 0.0))
            for name, joint in self._joints.items()}

    def joint_names(self):
        """Return the actuated joint names in model order."""
        return list(self._joints.keys())

    def has_joint(self, name):
        """Return ``True`` when ``name`` is a tracked actuated joint."""
        return name in self._joints

    def position(self, name):
        """Return the current normalized position of ``name``, or ``None``."""
        return self._positions.get(name)

    def _normalize(self, joint, value):
        """Clamp or wrap ``value`` per ``joint``'s type."""
        if joint.joint_type == 'continuous':
            return wrap_angle(value)
        lower = joint.limit.lower if joint.limit is not None else None
        upper = joint.limit.upper if joint.limit is not None else None
        return clamp(value, lower, upper)

    def set_position(self, name, value):
        """
        Command ``name`` to ``value``, returning the normalized result.

        Raises ``KeyError`` when ``name`` is not an actuated joint.
        """
        joint = self._joints.get(name)
        if joint is None:
            raise KeyError(name)
        normalized = self._normalize(joint, value)
        self._positions[name] = normalized
        return normalized

    def set_positions(self, mapping):
        """Command several joints at once, silently skipping unknown names."""
        for name, value in mapping.items():
            if name in self._joints:
                self.set_position(name, value)

    def joint_state(self):
        """Return ``(names, positions)`` snapshots ready to publish."""
        names = self.joint_names()
        return names, [self._positions[name] for name in names]


def main(args=None):
    """Run the joint-state adapter node: rebuild on edits, publish states."""
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSDurabilityPolicy, QoSProfile
    from sensor_msgs.msg import JointState
    from std_msgs.msg import String

    from urdf_live_editor.model.robot_model import RobotModel, URDFParseError

    rclpy.init(args=args)
    node = Node('joint_state_adapter_node')
    publish_rate = node.declare_parameter('publish_rate_hz', 30.0).value

    adapter = JointStateAdapter()
    states_pub = node.create_publisher(JointState, 'joint_states', 10)

    latched = QoSProfile(depth=1)
    latched.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL

    def on_description(msg):
        try:
            model = RobotModel.from_string(msg.data)
        except URDFParseError as exc:
            node.get_logger().warn('ignoring malformed robot_description: %s'
                                   % exc)
            return
        adapter.set_model(model)
        node.get_logger().info(
            'tracking %d actuated joint(s): %s'
            % (len(adapter.joint_names()), ', '.join(adapter.joint_names())))

    def on_command(msg):
        adapter.set_positions(dict(zip(msg.name, msg.position)))

    node.create_subscription(String, 'robot_description', on_description,
                             latched)
    node.create_subscription(JointState, 'joint_commands', on_command, 10)

    def publish():
        names, positions = adapter.joint_state()
        if not names:
            return
        msg = JointState()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.name = names
        msg.position = positions
        states_pub.publish(msg)

    node.create_timer(1.0 / float(publish_rate), publish)
    node.get_logger().info('joint_state_adapter_node started; '
                           'publishing /joint_states at %.1f Hz.'
                           % float(publish_rate))
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
