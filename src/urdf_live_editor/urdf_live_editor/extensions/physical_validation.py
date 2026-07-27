"""Deterministic collision-geometry and inertial validation (Milestone 6).

The Milestone 1 validators check *structure* — well-formedness, unique names, a
single connected tree, per-joint rules. They deliberately say nothing about the
*physical* plausibility of a model, because a topologically perfect URDF can
still be unsimulatable: a link with zero mass, a non-positive-definite inertia
tensor, or a collision box with a negative dimension will make Gazebo (or any
dynamics engine) misbehave or reject the model.

This module fills that gap. Given a URDF string it parses every link's
``<inertial>`` and ``<collision>``/``<visual>`` geometry and returns a
:class:`~urdf_live_editor.extensions.report.Report` describing what is wrong and
how serious it is. The checks are:

Inertial
    * missing ``<inertial>`` on a link  → WARNING (static/world links are fine,
      but a moving link almost always needs mass);
    * ``mass`` missing, non-numeric, ``<= 0``  → ERROR;
    * inertia tensor not symmetric-positive-definite  → ERROR (physically a
      rigid body's inertia tensor is always SPD);
    * principal moments violating the triangle inequality
      (``I1 + I2 >= I3``)  → WARNING (implausible mass distribution, but some
      simulators tolerate it).

Collision / visual geometry
    * link with an ``<inertial>`` but no ``<collision>``  → INFO (it will not
      collide in simulation, which is sometimes intentional);
    * a geometry primitive with a non-positive dimension
      (box size, cylinder/sphere radius, cylinder length, mesh scale)  → ERROR.

The eigenvalue computation for the triangle-inequality check uses a closed-form
solution for symmetric 3×3 matrices, so this module has **no NumPy or SciPy
dependency** and stays importable in the same minimal environment as the rest of
the deterministic core.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .report import Report, Severity, _Builder

__all__ = [
    "InertialInfo",
    "validate_physical",
    "symmetric_eigenvalues_3x3",
    "is_positive_definite_3x3",
]

# Tolerance for treating a near-zero float as zero (masses, determinants).
_EPS = 1e-9


# --------------------------------------------------------------------------- #
# Parsed inertial view
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class InertialInfo:
    """The inertial data of a single link, as declared in the URDF."""

    link: str
    mass: Optional[float]
    # Full symmetric inertia tensor components (URDF ``<inertia>`` attributes).
    ixx: float = 0.0
    ixy: float = 0.0
    ixz: float = 0.0
    iyy: float = 0.0
    iyz: float = 0.0
    izz: float = 0.0
    has_origin: bool = False

    def tensor(self) -> List[List[float]]:
        """Return the 3×3 symmetric inertia matrix."""
        return [
            [self.ixx, self.ixy, self.ixz],
            [self.ixy, self.iyy, self.iyz],
            [self.ixz, self.iyz, self.izz],
        ]


# --------------------------------------------------------------------------- #
# Linear-algebra helpers (dependency-free)
# --------------------------------------------------------------------------- #
def _det_3x3(m: List[List[float]]) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def is_positive_definite_3x3(m: List[List[float]], *, rtol: float = 1e-9) -> bool:
    """Sylvester's criterion: a symmetric matrix is SPD iff all leading
    principal minors are strictly positive.

    Thresholds are scaled by the matrix magnitude (each minor of order ``k``
    scales like ``scale**k``) so the test is robust for both large and very
    small inertia tensors — a valid ``diag(1e-3, 1e-3, 1e-3)`` tensor has a
    determinant of ``1e-9`` yet is clearly positive-definite.
    """
    scale = max((abs(v) for row in m for v in row), default=0.0)
    if scale <= 0.0:
        return False
    minor1 = m[0][0]
    minor2 = m[0][0] * m[1][1] - m[0][1] * m[1][0]
    minor3 = _det_3x3(m)
    return (
        minor1 > rtol * scale
        and minor2 > rtol * scale ** 2
        and minor3 > rtol * scale ** 3
    )


def symmetric_eigenvalues_3x3(m: List[List[float]]) -> Tuple[float, float, float]:
    """Return the three eigenvalues of a symmetric 3×3 matrix, ascending.

    Uses the closed-form solution (a specialization of the analytic algorithm
    for symmetric matrices) — exact for symmetric input, no iteration and no
    external dependency.
    """
    a11, a12, a13 = m[0]
    _, a22, a23 = m[1]
    _, _, a33 = m[2]

    p1 = a12 * a12 + a13 * a13 + a23 * a23
    if p1 <= _EPS:
        # Already diagonal; eigenvalues are the diagonal entries.
        return tuple(sorted((a11, a22, a33)))  # type: ignore[return-value]

    q = (a11 + a22 + a33) / 3.0
    p2 = (
        (a11 - q) ** 2
        + (a22 - q) ** 2
        + (a33 - q) ** 2
        + 2.0 * p1
    )
    p = math.sqrt(p2 / 6.0)

    # B = (1/p) (A - qI)
    b = [
        [(a11 - q) / p, a12 / p, a13 / p],
        [a12 / p, (a22 - q) / p, a23 / p],
        [a13 / p, a23 / p, (a33 - q) / p],
    ]
    r = _det_3x3(b) / 2.0
    # Clamp for numerical safety before acos.
    r = max(-1.0, min(1.0, r))
    phi = math.acos(r) / 3.0

    eig1 = q + 2.0 * p * math.cos(phi)                       # largest
    eig3 = q + 2.0 * p * math.cos(phi + 2.0 * math.pi / 3.0)  # smallest
    eig2 = 3.0 * q - eig1 - eig3                              # middle
    return tuple(sorted((eig1, eig2, eig3)))  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# URDF parsing
# --------------------------------------------------------------------------- #
def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_inertial(link_el: ET.Element, link_name: str) -> Optional[InertialInfo]:
    inertial = link_el.find("inertial")
    if inertial is None:
        return None
    mass_el = inertial.find("mass")
    mass = _parse_float(mass_el.get("value")) if mass_el is not None else None
    inertia_el = inertial.find("inertia")
    comps = {"ixx": 0.0, "ixy": 0.0, "ixz": 0.0, "iyy": 0.0, "iyz": 0.0, "izz": 0.0}
    if inertia_el is not None:
        for key in comps:
            parsed = _parse_float(inertia_el.get(key))
            comps[key] = parsed if parsed is not None else math.nan
    return InertialInfo(
        link=link_name,
        mass=mass,
        has_origin=inertial.find("origin") is not None,
        **comps,
    )


def _child_link_names(root: ET.Element) -> set:
    """Links that appear as a joint child (i.e. non-root candidates)."""
    children = set()
    for joint in root.findall("joint"):
        child_el = joint.find("child")
        if child_el is not None and child_el.get("link"):
            children.add(child_el.get("link"))
    return children


# Geometry primitives and the attributes that must be strictly positive.
def _check_geometry_dims(geom: ET.Element, subject: str, kind: str, out: _Builder) -> None:
    box = geom.find("box")
    if box is not None:
        size = (box.get("size") or "").split()
        for idx, raw in enumerate(size):
            val = _parse_float(raw)
            if val is not None and val <= _EPS:
                out.error(
                    "geometry_nonpositive",
                    f"{kind} box of link '{subject}' has non-positive size "
                    f"component {idx} ({raw})",
                    subject,
                )
    cyl = geom.find("cylinder")
    if cyl is not None:
        for attr in ("radius", "length"):
            val = _parse_float(cyl.get(attr))
            if val is not None and val <= _EPS:
                out.error(
                    "geometry_nonpositive",
                    f"{kind} cylinder of link '{subject}' has non-positive "
                    f"{attr} ({cyl.get(attr)})",
                    subject,
                )
    sph = geom.find("sphere")
    if sph is not None:
        val = _parse_float(sph.get("radius"))
        if val is not None and val <= _EPS:
            out.error(
                "geometry_nonpositive",
                f"{kind} sphere of link '{subject}' has non-positive radius "
                f"({sph.get('radius')})",
                subject,
            )
    mesh = geom.find("mesh")
    if mesh is not None and mesh.get("scale"):
        for raw in mesh.get("scale").split():
            val = _parse_float(raw)
            if val is not None and val <= _EPS:
                out.error(
                    "geometry_nonpositive",
                    f"{kind} mesh of link '{subject}' has non-positive scale "
                    f"component ({raw})",
                    subject,
                )


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def validate_physical(urdf_xml: str, *, require_collision: bool = False) -> Report:
    """Validate inertial and collision/geometry plausibility of a URDF.

    Parameters
    ----------
    urdf_xml:
        A (Xacro-expanded) URDF document string.
    require_collision:
        When true, a link that has an inertial but no ``<collision>`` element is
        reported at ERROR rather than INFO. Useful when the model is destined
        for a physics simulation where collisions matter.

    Returns
    -------
    Report
        A finished report; ``report.ok`` is true when it holds no ERROR issues.

    Raises
    ------
    ValueError
        If the XML is malformed or the root is not ``<robot>``.
    """
    try:
        root = ET.fromstring(urdf_xml)
    except ET.ParseError as exc:
        raise ValueError(f"URDF is not well-formed XML: {exc}") from exc
    if root.tag != "robot":
        raise ValueError(f"expected <robot> root element, got <{root.tag}>")

    out = _Builder("physical_validation")
    child_links = _child_link_names(root)

    for link in root.findall("link"):
        name = link.get("name")
        if not name:
            continue

        info = _parse_inertial(link, name)
        if info is None:
            # A root/world anchor link legitimately may have no inertia; a link
            # that hangs off a joint almost never should.
            severity = Severity.WARNING if name in child_links else Severity.INFO
            out.add(
                severity,
                "inertial_missing",
                f"link '{name}' has no <inertial> element",
                name,
            )
        else:
            _validate_inertial(info, out)

        _validate_collision(link, name, info is not None, require_collision, out)

    return out.build()


def _validate_inertial(info: InertialInfo, out: _Builder) -> None:
    name = info.link
    if info.mass is None:
        out.error("mass_missing", f"link '{name}' has an inertial with no mass value", name)
    elif math.isnan(info.mass) or info.mass <= _EPS:
        out.error(
            "mass_nonpositive",
            f"link '{name}' has non-positive mass ({info.mass})",
            name,
        )

    tensor = info.tensor()
    if any(math.isnan(v) for row in tensor for v in row):
        out.error(
            "inertia_incomplete",
            f"link '{name}' has an inertia tensor with missing components",
            name,
        )
        return

    # An all-zero tensor is a common placeholder; flag it distinctly.
    if all(abs(v) <= _EPS for row in tensor for v in row):
        out.error(
            "inertia_zero",
            f"link '{name}' has an all-zero inertia tensor",
            name,
        )
        return

    if not is_positive_definite_3x3(tensor):
        out.error(
            "inertia_not_spd",
            f"link '{name}' inertia tensor is not positive-definite",
            name,
        )
        return

    # Physically, principal moments of inertia satisfy the triangle inequality.
    i1, i2, i3 = symmetric_eigenvalues_3x3(tensor)
    if i1 + i2 < i3 - _EPS:
        out.warn(
            "inertia_triangle_inequality",
            f"link '{name}' principal moments violate the triangle inequality "
            f"({i1:.6g} + {i2:.6g} < {i3:.6g})",
            name,
        )

    if not info.has_origin:
        out.info(
            "inertial_origin_default",
            f"link '{name}' inertial has no <origin>; center of mass assumed at "
            "the link frame origin",
            name,
        )


def _validate_collision(
    link_el: ET.Element,
    name: str,
    has_inertial: bool,
    require_collision: bool,
    out: _Builder,
) -> None:
    collisions = link_el.findall("collision")
    if not collisions and has_inertial:
        severity = Severity.ERROR if require_collision else Severity.INFO
        out.add(
            severity,
            "collision_missing",
            f"link '{name}' has mass but no <collision> geometry; it will not "
            "collide in simulation",
            name,
        )
    for collision in collisions:
        geom = collision.find("geometry")
        if geom is None:
            out.error(
                "collision_geometry_missing",
                f"link '{name}' has a <collision> with no <geometry>",
                name,
            )
        else:
            _check_geometry_dims(geom, name, "collision", out)
    for visual in link_el.findall("visual"):
        geom = visual.find("geometry")
        if geom is not None:
            _check_geometry_dims(geom, name, "visual", out)
