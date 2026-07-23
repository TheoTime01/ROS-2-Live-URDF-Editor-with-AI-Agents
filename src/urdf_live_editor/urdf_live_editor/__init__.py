"""``urdf_live_editor`` — deterministic core for the ROS 2 Live URDF Editor.

This package holds robotics/validation logic with **no** dependency on any LLM
or network service, so it can be fully unit-tested offline. Milestone 5 adds the
:mod:`~urdf_live_editor.observability` (logging, diagnostics, audit) and
:mod:`~urdf_live_editor.integration` (launch/config sync) subpackages.
"""

__all__ = ["observability", "integration"]
