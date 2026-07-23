"""``urdf_ai_agents`` — Claude Agent SDK layer for the URDF live editor.

Agents in this package never mutate the active ``robot_description`` directly;
they route every change through the deterministic staged-validation pipeline in
``urdf_live_editor``. Milestone 5 contributes the Launch/Integration Agent.
"""

__all__ = ["agents"]
