# Architecture

This document tracks the concrete architecture of the workspace as it is built
out. For the product overview and the milestone roadmap, see the
[README](../README.md) and [ROADMAP](../ROADMAP.md).

## Workspace layout

The repository is a standard ROS 2 (`colcon`) workspace with two packages under
`src/`:

- **`urdf_live_editor`** — the deterministic robotics core. It has no dependency
  on any LLM and owns URDF loading, the validation engine, the staged-edit
  pipeline, and the version store. Everything here is testable offline.
- **`urdf_ai_agents`** — the Claude Agent SDK layer. It never mutates the active
  `robot_description` directly; it only produces `EditOperation` JSON and calls
  the same staged-validation interfaces a human uses, exposed as MCP tools.

The hard boundary between the two packages is what guarantees the AI layer can
never bypass deterministic validation.

## Deterministic core (Milestone 1)

The `urdf_live_editor` package now contains a working, AI-free robotics core.
Everything below is plain Python, imports no ROS at module load, and is covered
by offline unit and golden-model tests.

### Model

`model/robot_model.py` holds the in-memory representation. A `RobotModel` is a
set of named `Link` and `Joint` objects; it parses from a plain-URDF string
(`from_string`) and serializes back (`to_string`), so it round-trips through the
`robot_description` parameter. Xacro is expanded upstream in `urdf_source_node`,
so the core only ever sees plain URDF. Link bodies (visual/collision/inertial)
are preserved verbatim for round-tripping; joints are fully structured.

### Validation engine

`validation/` is a composable set of deterministic checks, each returning a
`ValidationResult` (an ordered list of severity-tagged `ValidationIssue`s):

- `schema.py` — well-formedness, present/unique link and joint names, and
  parent/child references that resolve to declared links.
- `topology.py` — a single connected tree: exactly one root, no cycles,
  no multi-parent links, no disconnected components.
- `joint_rules.py` — per-type rules for `revolute`, `continuous`, `prismatic`,
  and `fixed` joints (axis presence/non-degeneracy, finite ordered limits,
  positive effort/velocity).

`validation/engine.py` composes the three into `validate_model` and adds
`validate_urdf_string`, which gates on well-formedness before parsing.

### Staged edits, versioning, and the coordinator

`model/edit_ops.py` defines the `EditOperation` vocabulary (`add_link`,
`add_joint`, `update_joint`, `remove_joint`, `set_joint_limit`,
`set_joint_axis`, `rename`, …). Each operation is a small JSON-serializable
value object that produces a *new* model, never mutating its input, and enforces
only its own preconditions — structural validity is left to the engine.

`model/version_store.py` keeps an append-only history of immutable `Version`
snapshots. Rollback appends a copy of an earlier version rather than deleting
history, so the audit trail (with a per-version diff) is always complete.

`ModelUpdateCoordinator` (in `model_update_coordinator_node.py`) ties it
together and is the single trusted path by which the model changes: it applies
an edit to a *copy* of the current model, validates the candidate, and commits a
new version only when there are no error-severity issues — otherwise the edit is
rejected and the live model is untouched. This is the interface a human, the web
API, and later the AI layer all share, which is what guarantees the AI can never
bypass validation.

### Tests

Unit tests cover each module; `test/test_golden_models.py` runs a corpus of
known-good and known-broken URDFs under `src/urdf_live_editor/test/models/`
against the engine and asserts the expected verdict and diagnostic codes. The
whole suite runs under `colcon test` alongside `ament_flake8`, `ament_pep257`,
and `ament_copyright`.

The sample robot lives at
[`models/sample_arm/sample_arm.urdf.xacro`](../models/sample_arm/sample_arm.urdf.xacro).
