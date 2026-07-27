"""Multi-robot / multi-model session management (Milestone 6).

Everything up to Milestone 5 assumed a single active ``robot_description``. This
module lets several models be edited and visualized side by side in one live
session — a mobile base plus a manipulator, two arms in a cell, a robot and its
fixture — without their names, namespaces, or TF frames colliding.

The key idea is deterministic *namespacing*. Each model lives in a
:class:`ModelSession` with a unique ROS ``namespace`` and a matching TF
``frame_prefix``. :func:`namespace_urdf` rewrites a URDF so that every link and
joint name — and every internal ``parent``/``child`` reference — is prefixed,
producing a model that can be published into a shared TF tree with no frame
clashes. A :class:`SessionRegistry` enforces uniqueness up front and can report
the frames a combined scene would contain, flagging any residual collision.

As with the rest of the extensions layer this is pure, offline Python: it
manipulates URDF strings and returns dataclasses / reports, so it is fully
unit-testable and the AI layer can drive it but never bypass its guarantees.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..integration.launch_sync import ModelSummary, extract_model_summary
from .report import Report, _Builder

__all__ = [
    "ModelSession",
    "SessionRegistry",
    "namespace_urdf",
    "is_valid_namespace",
    "DuplicateSessionError",
]

# A ROS name token: starts with a letter/underscore, then word chars.
_NAME_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DuplicateSessionError(ValueError):
    """Raised when a session id or namespace would collide with an existing one."""


def is_valid_namespace(namespace: str) -> bool:
    """True if ``namespace`` is a legal single ROS name token (no slashes)."""
    return bool(_NAME_TOKEN.match(namespace or ""))


# --------------------------------------------------------------------------- #
# URDF namespacing
# --------------------------------------------------------------------------- #
def namespace_urdf(urdf_xml: str, prefix: str, *, separator: str = "_") -> str:
    """Return a copy of ``urdf_xml`` with every link/joint name prefixed.

    Both link and joint ``name`` attributes are rewritten to ``{prefix}{sep}{name}``,
    and every ``<parent link=...>`` / ``<child link=...>`` reference is updated to
    match, so the resulting URDF is internally consistent and can coexist with
    other prefixed models in a shared TF tree.

    Parameters
    ----------
    prefix:
        The session prefix (typically the session namespace). Must be a valid
        name token.
    separator:
        Placed between prefix and the original name (default ``"_"``).

    Raises
    ------
    ValueError
        If the prefix is invalid or the URDF is malformed / not a ``<robot>``.
    """
    if not is_valid_namespace(prefix):
        raise ValueError(f"invalid namespace prefix: {prefix!r}")
    try:
        root = ET.fromstring(urdf_xml)
    except ET.ParseError as exc:
        raise ValueError(f"URDF is not well-formed XML: {exc}") from exc
    if root.tag != "robot":
        raise ValueError(f"expected <robot> root element, got <{root.tag}>")

    def prefixed(name: str) -> str:
        return f"{prefix}{separator}{name}"

    for link in root.findall("link"):
        name = link.get("name")
        if name:
            link.set("name", prefixed(name))

    for joint in root.findall("joint"):
        name = joint.get("name")
        if name:
            joint.set("name", prefixed(name))
        for ref_tag in ("parent", "child"):
            ref = joint.find(ref_tag)
            if ref is not None and ref.get("link"):
                ref.set("link", prefixed(ref.get("link")))

    # ``mimic`` joints reference another joint by name; keep them consistent.
    for mimic in root.iter("mimic"):
        if mimic.get("joint"):
            mimic.set("joint", prefixed(mimic.get("joint")))

    return ET.tostring(root, encoding="unicode")


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModelSession:
    """One model within a multi-model live session."""

    session_id: str
    namespace: str
    urdf: str
    name: str = ""
    frame_prefix: str = ""

    def __post_init__(self) -> None:
        if not is_valid_namespace(self.namespace):
            raise ValueError(f"invalid namespace: {self.namespace!r}")

    @property
    def effective_frame_prefix(self) -> str:
        """The TF frame prefix — defaults to ``{namespace}_`` when unset."""
        return self.frame_prefix or f"{self.namespace}_"

    def summary(self) -> ModelSummary:
        """Structural summary of this session's (un-prefixed) model."""
        return extract_model_summary(self.urdf)

    def namespaced_urdf(self, *, separator: str = "_") -> str:
        """This session's URDF with all names prefixed by its namespace."""
        return namespace_urdf(self.urdf, self.namespace, separator=separator)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "namespace": self.namespace,
            "name": self.name,
            "frame_prefix": self.effective_frame_prefix,
        }


class SessionRegistry:
    """A registry of active :class:`ModelSession` objects.

    Enforces that both ``session_id`` and ``namespace`` are unique across the
    registry, so no two models can shadow each other on ROS topics or in TF.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, ModelSession] = {}
        self._namespaces: Dict[str, str] = {}  # namespace -> session_id

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, session_id: object) -> bool:
        return session_id in self._sessions

    def add(self, session: ModelSession) -> ModelSession:
        if session.session_id in self._sessions:
            raise DuplicateSessionError(
                f"session id already registered: {session.session_id!r}"
            )
        if session.namespace in self._namespaces:
            owner = self._namespaces[session.namespace]
            raise DuplicateSessionError(
                f"namespace {session.namespace!r} already used by session {owner!r}"
            )
        self._sessions[session.session_id] = session
        self._namespaces[session.namespace] = session.session_id
        return session

    def remove(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            self._namespaces.pop(session.namespace, None)

    def get(self, session_id: str) -> Optional[ModelSession]:
        return self._sessions.get(session_id)

    def list(self) -> List[ModelSession]:
        """All sessions, ordered by session id."""
        return [self._sessions[k] for k in sorted(self._sessions)]

    def combined_frames(self) -> List[str]:
        """All TF frame names the combined scene would publish, sorted.

        Each session contributes its links prefixed by its frame prefix, which
        is how ``robot_state_publisher`` (with ``frame_prefix``) names them.
        """
        frames: List[str] = []
        for session in self.list():
            prefix = session.effective_frame_prefix
            for link in session.summary().links:
                frames.append(f"{prefix}{link}")
        return sorted(frames)

    def check_scene(self) -> Report:
        """Report collisions that would occur in the combined multi-model scene.

        With unique namespaces enforced at :meth:`add` time, frame collisions
        should not occur; this catches the residual case where two sessions
        chose frame prefixes that happen to produce identical frame names
        (e.g. overlapping custom ``frame_prefix`` values).
        """
        out = _Builder("multi_model_scene")
        seen: Dict[str, str] = {}
        for session in self.list():
            prefix = session.effective_frame_prefix
            for link in sorted(session.summary().links):
                frame = f"{prefix}{link}"
                if frame in seen:
                    out.error(
                        "frame_collision",
                        f"frame '{frame}' is produced by both session "
                        f"'{seen[frame]}' and '{session.session_id}'",
                        frame,
                    )
                else:
                    seen[frame] = session.session_id
        if not out.build().issues:
            out.info(
                "scene_ok",
                f"{len(self)} session(s) contribute "
                f"{len(seen)} unique frames with no collisions",
            )
        return out.build()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": len(self),
            "sessions": [s.to_dict() for s in self.list()],
            "frames": self.combined_frames(),
        }
