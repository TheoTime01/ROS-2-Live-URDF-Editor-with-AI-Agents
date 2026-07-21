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

## Milestone 0 status

This is the scaffolding milestone. Both packages build with `ament_python`,
expose ROS 2 entry points as skeleton nodes, and ship a lint + test setup that
runs under `colcon test` (`ament_flake8`, `ament_pep257`, `ament_copyright`,
and `pytest`). The behaviour of the nodes and of the `validation/` and `model/`
modules is filled in from Milestone 1 onward.

The sample robot lives at
[`models/sample_arm/sample_arm.urdf.xacro`](../models/sample_arm/sample_arm.urdf.xacro)
and is exercised by a parse test that locks in the test harness.
