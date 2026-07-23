"""Launch/config integration utilities (Milestone 5).

Deterministic detection and repair-planning of drift between a robot model and
the launch/config artifacts that reference it. The Launch/Integration *Agent*
lives in ``urdf_ai_agents`` and is only a thin explanatory wrapper over the
planners here.
"""

from __future__ import annotations

from .launch_sync import (
    MOVABLE_JOINT_TYPES,
    ChangeKind,
    JointInfo,
    ModelSummary,
    ReferenceIssue,
    SyncAction,
    SyncPlan,
    apply_config_sync,
    check_launch_references,
    extract_model_summary,
    load_yaml,
    plan_config_sync,
)

__all__ = [
    "MOVABLE_JOINT_TYPES",
    "ChangeKind",
    "JointInfo",
    "ModelSummary",
    "ReferenceIssue",
    "SyncAction",
    "SyncPlan",
    "apply_config_sync",
    "check_launch_references",
    "extract_model_summary",
    "load_yaml",
    "plan_config_sync",
]
