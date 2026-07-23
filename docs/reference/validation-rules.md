# Validation rules

Validation runs in two independent passes on the **staged** candidate. The
deterministic pass is authoritative — a change is applied only if it succeeds.
The AI pass never overrides it; it only adds explanations and repair
suggestions.

The web front-end (`web/js/urdf.js`) implements the same rules as the Python
core so the UI can validate instantly and agree with the server.

## Deterministic checks (authoritative)

### 1. Well-formedness

The URDF/Xacro parses and expands without error, and the document root is
`<robot>`.

### 2. Schema / structure

- Every `link` and `joint` has a **unique** name.
- Every joint references an **existing** parent and child link.
- Every joint declares both a parent and a child.

| Code | Meaning |
|---|---|
| `DUPLICATE_LINK` / `DUPLICATE_JOINT` | name used more than once |
| `BAD_PARENT` / `BAD_CHILD` | joint references a link that does not exist |
| `MISSING_PARENT` / `MISSING_CHILD` | joint is missing a parent/child |
| `UNKNOWN_JOINT_TYPE` | type is not one of the URDF joint types |

### 3. Topology

The link/joint graph must form a single connected tree with exactly one root and
no cycles; no orphan links.

| Code | Meaning |
|---|---|
| `NO_ROOT` | every link is a child (a cycle, or nothing to root at) |
| `MULTIPLE_ROOTS` | more than one link has no parent |
| `CYCLE` | a cycle was found while walking from the root |
| `ORPHAN_LINKS` (warning) | links not reachable from the root |

### 4. Per-joint rules

| Joint type | Requires | Must not have | Runtime |
|---|---|---|---|
| `revolute` | `<axis>`, finite `lower ≤ upper` | — | clamped to `[lower, upper]` |
| `prismatic` | `<axis>`, finite `lower ≤ upper` (meters) | — | clamped to `[lower, upper]` |
| `continuous` | `<axis>` | finite `lower`/`upper` | wraps modulo `2π` |
| `fixed` | — | any motion `<limit>` | static (no DOF) |

| Code | Meaning |
|---|---|
| `MISSING_AXIS` | movable joint has no `<axis>` |
| `MISSING_LIMIT` | revolute/prismatic joint lacks finite `lower`/`upper` |
| `INVERTED_LIMIT` | `lower > upper` |
| `NEGATIVE_LIMIT` | `effort` or `velocity` is negative |
| `CONTINUOUS_HAS_LIMIT` (warning) | continuous joint carries finite limits |
| `FIXED_HAS_LIMIT` | fixed joint carries a motion limit |

### 5. Units & ranges

Angular limits are in radians, prismatic limits in meters; `effort` and
`velocity` limits, if present, are non-negative.

## AI-assisted checks (advisory)

- A human-readable explanation of *why* a deterministic check failed.
- Detection of likely-unintended but technically valid changes (e.g. an axis
  that makes the chain kinematically degenerate).
- **Suggested repairs** returned as candidate `EditOperation`s — which must
  themselves pass deterministic validation before they can be applied.

## `ValidationResult`

```json
{
  "valid": false,
  "errors": [
    {"code": "MISSING_LIMIT", "severity": "error", "joint": "elbow",
     "message": "revolute joint 'elbow' requires finite lower/upper limits."}
  ],
  "warnings": [],
  "suggested_repairs": [
    {"operation": "set_joint_limit",
     "target": {"name": "elbow", "limit": {"lower": -1.5708, "upper": 1.5708}},
     "reason": "Add symmetric limits so the revolute joint is bounded."}
  ]
}
```
