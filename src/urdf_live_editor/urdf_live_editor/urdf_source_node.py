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
Load and hot-reload a URDF/Xacro model from disk.

:class:`UrdfSource` is the file-facing edge of the deterministic core. It reads
a ``.urdf`` or ``.urdf.xacro`` file, expands Xacro when needed, and detects
edits by hashing the raw source, so a poll re-expands only when the file
actually changed. The change detection and expansion are plain Python and
testable offline; ``main`` wraps the source in a ROS 2 node that latches
``robot_description`` and re-publishes it on every reload.
"""

import hashlib


class UrdfSource:
    """A single URDF/Xacro file with change detection and hot-reload."""

    def __init__(self, path, mappings=None):
        """Track ``path``, with optional Xacro ``mappings`` (name -> value)."""
        self._path = path
        self._mappings = dict(mappings or {})
        self._signature = None
        self._callbacks = []

    @property
    def path(self):
        """Return the tracked file path."""
        return self._path

    def on_change(self, callback):
        """Register ``callback(urdf_str)`` to run on every reload."""
        self._callbacks.append(callback)

    def _raw_bytes(self):
        """Return the raw file contents as bytes."""
        with open(self._path, 'rb') as handle:
            return handle.read()

    @staticmethod
    def _hash(data):
        """Return a stable content signature for ``data``."""
        return hashlib.sha1(data).hexdigest()

    def _expand(self, raw):
        """Expand Xacro if needed, returning plain URDF text."""
        if self._path.endswith('.xacro'):
            import xacro
            document = xacro.process_file(self._path, mappings=self._mappings)
            return document.toprettyxml(indent='  ')
        return raw.decode('utf-8')

    def load(self):
        """Read and expand the file, refreshing the change signature."""
        raw = self._raw_bytes()
        self._signature = self._hash(raw)
        return self._expand(raw)

    def has_changed(self):
        """Return ``True`` when the file differs from the last load."""
        try:
            return self._hash(self._raw_bytes()) != self._signature
        except FileNotFoundError:
            return False

    def poll(self):
        """Reload and notify callbacks when the file changed; return the URDF.

        Returns the freshly loaded URDF string when a change was detected and
        applied, or ``None`` when nothing changed.
        """
        if not self.has_changed():
            return None
        urdf = self.load()
        for callback in self._callbacks:
            callback(urdf)
        return urdf


def main(args=None):
    """Start the URDF source node: latch robot_description, poll for edits."""
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSDurabilityPolicy, QoSProfile
    from std_msgs.msg import String

    rclpy.init(args=args)
    node = Node('urdf_source_node')
    model_path = node.declare_parameter('model_path', '').value
    reload_period = node.declare_parameter('reload_period_sec', 1.0).value

    latched = QoSProfile(depth=1)
    latched.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL
    publisher = node.create_publisher(String, 'robot_description', latched)

    def publish(urdf):
        publisher.publish(String(data=urdf))
        node.get_logger().info('published robot_description (%d bytes).'
                               % len(urdf))

    if model_path:
        source = UrdfSource(model_path)
        source.on_change(publish)
        publish(source.load())
        node.create_timer(reload_period, source.poll)
    else:
        node.get_logger().warn('no model_path parameter set; idle.')

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
