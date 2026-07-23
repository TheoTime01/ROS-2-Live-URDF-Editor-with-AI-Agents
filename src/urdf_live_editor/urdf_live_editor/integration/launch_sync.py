"""Deterministic launch/config drift detection and repair planning.

When the robot model changes (a joint is added, removed, renamed, or retyped),
several *non-model* artifacts must be kept in step with it:

* per-joint policy/config files that enumerate joints
  (e.g. ``config/validation_policy.yaml``),
* launch-file references to the model, the RViz config, and controller configs,
* any joint list a GUI or controller manager consumes.

This module computes, **deterministically**, the difference between what a model
contains and what a config declares, and produces a :class:`SyncPlan` describing
exactly what must change. The *Launch/Integration Agent* (in ``urdf_ai_agents``)
is only a thin wrapper that explains this plan in natural language and, on
request, applies it — it can never invent a change the deterministic planner did
not authorize. That preserves the project's core principle that the AI layer
cannot bypass deterministic logic.

Nothing here depends on ROS or an LLM, so it is fully unit-testable offline. The
only optional dependency is PyYAML, used by the file-loading convenience
helpers; the core planning functions operate on plain Python structures.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

__all__ = [
    "JointInfo",
    "ModelSummary",
    "extract_model_summary",
    "ChangeKind",
    "SyncAction",
    "SyncPlan",
    "ReferenceIssue",
    "plan_config_sync",
    "apply_config_sync",
    "check_launch_references",
    "load_yaml",
    "MOVABLE_JOINT_TYPES",
]

# Joint types that expose a runtime DOF and therefore need a config entry.
MOVABLE_JOINT_TYPES = frozenset({"revolute", "continuous", "prismatic"})
_ALL_JOINT_TYPES = MOVABLE_JOINT_TYPES | frozenset({"fixed", "floating", "planar"})


# --------------------------------------------------------------------------- #
# Model summary extraction
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class JointInfo:
    """The subset of a URDF joint that launch/config artifacts care about."""

    name: str
    type: str
    parent: Optional[str] = None
    child: Optional[str] = None

    @property
    def is_movable(self) -> bool:
        return self.type in MOVABLE_JOINT_TYPES


@dataclass(frozen=True)
class ModelSummary:
    """A lightweight structural view of a URDF model.

    This is intentionally *not* the full Milestone 1 model object — it is only
    what the launch/config synchronizer needs, so this module stays decoupled
    from (and testable without) the deterministic core's richer model classes.
    """

    links: Set[str] = field(default_factory=set)
    joints: Dict[str, JointInfo] = field(default_factory=dict)
    root: Optional[str] = None

    @property
    def movable_joints(self) -> Dict[str, JointInfo]:
        return {n: j for n, j in self.joints.items() if j.is_movable}

    def joint_names(self, movable_only: bool = False) -> List[str]:
        source = self.movable_joints if movable_only else self.joints
        return sorted(source)


def extract_model_summary(urdf_xml: str) -> ModelSummary:
    """Parse a (already Xacro-expanded) URDF string into a :class:`ModelSummary`.

    Raises
    ------
    ValueError
        If the XML is malformed or is not a ``<robot>`` document.
    """
    try:
        root = ET.fromstring(urdf_xml)
    except ET.ParseError as exc:
        raise ValueError(f"URDF is not well-formed XML: {exc}") from exc
    if root.tag != "robot":
        raise ValueError(f"expected <robot> root element, got <{root.tag}>")

    links: Set[str] = set()
    for link in root.findall("link"):
        name = link.get("name")
        if name:
            links.add(name)

    joints: Dict[str, JointInfo] = {}
    children: Set[str] = set()
    for joint in root.findall("joint"):
        name = joint.get("name")
        if not name:
            continue
        jtype = (joint.get("type") or "").strip().lower()
        parent_el = joint.find("parent")
        child_el = joint.find("child")
        parent = parent_el.get("link") if parent_el is not None else None
        child = child_el.get("link") if child_el is not None else None
        if child:
            children.add(child)
        joints[name] = JointInfo(name=name, type=jtype, parent=parent, child=child)

    # The root link is the one that is never a child (best-effort; the real
    # topology check lives in the deterministic core's topology validator).
    roots = sorted(links - children)
    root_link = roots[0] if len(roots) == 1 else (roots[0] if roots else None)
    return ModelSummary(links=links, joints=joints, root=root_link)


# --------------------------------------------------------------------------- #
# Sync planning
# --------------------------------------------------------------------------- #
class ChangeKind(str, Enum):
    """Why a config entry is out of sync with the model."""

    ADD = "add"            # joint exists in model but not in config
    REMOVE = "remove"      # config entry has no matching model joint (stale)
    RETYPE = "retype"      # joint type changed (config must be updated)


@dataclass(frozen=True)
class SyncAction:
    """A single deterministic change required to bring config into sync."""

    kind: ChangeKind
    joint: str
    detail: str = ""
    old_type: Optional[str] = None
    new_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "joint": self.joint,
            "detail": self.detail,
            "old_type": self.old_type,
            "new_type": self.new_type,
        }


@dataclass(frozen=True)
class SyncPlan:
    """The set of actions needed to reconcile a config with the model."""

    config_name: str
    actions: List[SyncAction] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not self.actions

    def of_kind(self, kind: ChangeKind) -> List[SyncAction]:
        return [a for a in self.actions if a.kind == kind]

    def summary(self) -> str:
        if self.in_sync:
            return f"{self.config_name}: in sync"
        counts = {k.value: len(self.of_kind(k)) for k in ChangeKind}
        parts = [f"{n} {k}" for k, n in counts.items() if n]
        return f"{self.config_name}: {', '.join(parts)}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_name": self.config_name,
            "in_sync": self.in_sync,
            "summary": self.summary(),
            "actions": [a.to_dict() for a in self.actions],
        }


def _config_joint_types(config: Mapping[str, Any], joints_key: str) -> Dict[str, Optional[str]]:
    """Extract ``{joint_name: declared_type_or_None}`` from a config mapping.

    Accepts two common shapes under ``config[joints_key]``:

    * a mapping ``{name: {type: ..., ...}}`` (per-joint override blocks), or
    * a list of names ``[name, ...]`` (a plain enumeration, no types).
    """
    section = config.get(joints_key)
    if section is None:
        return {}
    result: Dict[str, Optional[str]] = {}
    if isinstance(section, Mapping):
        for name, body in section.items():
            declared = None
            if isinstance(body, Mapping):
                t = body.get("type")
                declared = str(t).lower() if t is not None else None
            result[str(name)] = declared
    elif isinstance(section, Sequence) and not isinstance(section, (str, bytes)):
        for name in section:
            result[str(name)] = None
    else:  # pragma: no cover - defensive
        raise TypeError(f"unsupported {joints_key!r} section type: {type(section)!r}")
    return result


def plan_config_sync(
    model: ModelSummary,
    config: Mapping[str, Any],
    *,
    config_name: str = "config",
    joints_key: str = "joints",
    movable_only: bool = True,
) -> SyncPlan:
    """Compute the actions needed to reconcile ``config`` with ``model``.

    Parameters
    ----------
    movable_only:
        When true (default), only movable joints (revolute/continuous/prismatic)
        are expected to appear in the config, since ``fixed`` joints carry no
        runtime DOF. A ``fixed`` joint still present in the config is flagged for
        removal.
    """
    expected = model.movable_joints if movable_only else model.joints
    declared = _config_joint_types(config, joints_key)
    actions: List[SyncAction] = []

    # Additions and retypes (deterministic order by joint name).
    for name in sorted(expected):
        info = expected[name]
        if name not in declared:
            actions.append(
                SyncAction(
                    kind=ChangeKind.ADD,
                    joint=name,
                    detail=f"{info.type} joint present in model but absent from {config_name}",
                    new_type=info.type,
                )
            )
        else:
            declared_type = declared[name]
            if declared_type is not None and declared_type != info.type:
                actions.append(
                    SyncAction(
                        kind=ChangeKind.RETYPE,
                        joint=name,
                        detail=f"type changed {declared_type} -> {info.type}",
                        old_type=declared_type,
                        new_type=info.type,
                    )
                )

    # Removals: anything declared that is no longer an expected joint.
    for name in sorted(declared):
        if name not in expected:
            reason = "no longer in model"
            if name in model.joints and movable_only and not model.joints[name].is_movable:
                reason = f"joint is now '{model.joints[name].type}' (no runtime DOF)"
            actions.append(
                SyncAction(kind=ChangeKind.REMOVE, joint=name, detail=reason)
            )

    return SyncPlan(config_name=config_name, actions=actions)


def apply_config_sync(
    config: Mapping[str, Any],
    model: ModelSummary,
    plan: SyncPlan,
    *,
    joints_key: str = "joints",
    default_entry: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a **new** config dict with ``plan``'s actions applied.

    The input config is not mutated. New joint entries are created as mapping
    blocks carrying at least ``{"type": <joint_type>}`` merged with
    ``default_entry``; removals drop the entry; retypes update the ``type``
    field in place while preserving any other keys the operator set.
    """
    import copy

    new_config: Dict[str, Any] = copy.deepcopy(dict(config))
    section = new_config.get(joints_key)

    # Normalize the section to a mapping so we can add typed blocks uniformly.
    if section is None:
        section = {}
    elif isinstance(section, Sequence) and not isinstance(section, (str, bytes)):
        section = {str(name): {} for name in section}
    elif isinstance(section, Mapping):
        section = dict(section)
    else:  # pragma: no cover - defensive
        raise TypeError(f"unsupported {joints_key!r} section type: {type(section)!r}")

    for action in plan.actions:
        if action.kind is ChangeKind.ADD:
            entry: Dict[str, Any] = dict(default_entry or {})
            info = model.joints.get(action.joint)
            entry["type"] = info.type if info else action.new_type
            section[action.joint] = entry
        elif action.kind is ChangeKind.REMOVE:
            section.pop(action.joint, None)
        elif action.kind is ChangeKind.RETYPE:
            block = section.get(action.joint)
            if isinstance(block, Mapping):
                block = dict(block)
            else:
                block = {}
            block["type"] = action.new_type
            section[action.joint] = block

    new_config[joints_key] = section
    return new_config


# --------------------------------------------------------------------------- #
# Launch reference checks
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReferenceIssue:
    """A launch/config file that points at something missing on disk."""

    key: str
    path: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "path": self.path, "message": self.message}


def check_launch_references(
    references: Mapping[str, str],
    *,
    base_dir: str = ".",
) -> List[ReferenceIssue]:
    """Verify that each launch/config reference resolves to an existing file.

    ``references`` maps a logical name (e.g. ``"model"``, ``"rviz_config"``,
    ``"controllers"``) to a path. Relative paths are resolved against
    ``base_dir``. Returns one :class:`ReferenceIssue` per missing target, in a
    stable order.
    """
    issues: List[ReferenceIssue] = []
    for key in sorted(references):
        raw = references[key]
        if not raw:
            issues.append(ReferenceIssue(key=key, path=raw, message="empty path"))
            continue
        resolved = raw if os.path.isabs(raw) else os.path.join(base_dir, raw)
        if not os.path.exists(resolved):
            issues.append(
                ReferenceIssue(
                    key=key,
                    path=raw,
                    message=f"referenced {key} does not exist: {resolved}",
                )
            )
    return issues


# --------------------------------------------------------------------------- #
# Convenience loaders
# --------------------------------------------------------------------------- #
def load_yaml(path: str) -> Dict[str, Any]:
    """Load a YAML config file into a dict. Requires PyYAML."""
    import yaml  # imported lazily so the core has no hard dependency

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"expected a mapping at the top of {path}, got {type(data)!r}")
    return data
