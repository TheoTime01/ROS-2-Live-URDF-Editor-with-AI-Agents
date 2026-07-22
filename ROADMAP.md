# Development Roadmap

This document is the working roadmap for **ROS 2 Live URDF Editor with AI Agents**. The high-level milestone list also appears in the [README](README.md#roadmap); this file adds deliverables, acceptance criteria, and the concrete next steps.

**Status legend:** ☐ planned · ◐ in progress · ☑ done

---

## Guiding principles

1. **Deterministic core first.** Every AI capability is built on top of a robotics core that is fully testable without any API access. The AI layer can never bypass validation.
2. **Staged edits only.** Nothing mutates the active `robot_description` until it has passed deterministic validation on a staged candidate.
3. **Everything is auditable.** Every applied change produces a versioned diff and an audit entry.
4. **Ship testable slices.** Each milestone ends with something runnable and covered by tests.

---

## Milestone 0 — Project scaffolding

**Goal:** a buildable, tested, empty skeleton.

- ☑ Repository, README, and `.gitignore`.
- ☑ Two-package `colcon` workspace: `urdf_live_editor` (deterministic) and `urdf_ai_agents` (Claude Agent SDK).
- ☑ `package.xml` / `setup.py` for both packages; `colcon build` succeeds.
- ☑ CI pipeline: `colcon build`, lint (`ament_flake8`, `ament_pep257`, `ament_copyright`), and `pytest` on every push.
- ☑ Sample robot under `models/sample_arm/` used by demos and tests.

**Done when:** `colcon build && colcon test` passes green in CI on an empty-but-wired skeleton.

---

## Milestone 1 — Deterministic core (no AI)

**Goal:** the constraint engine and staged-edit pipeline exist and are trusted.

- ☑ `urdf_source_node` — load + hot-reload URDF/Xacro from disk (file watcher).
- ☑ Validation engine (`validation/`):
  - ☑ `schema.py` — well-formedness, unique names, parent/child references.
  - ☑ `topology.py` — single connected tree, one root, no cycles/orphans.
  - ☑ `joint_rules.py` — per-type rules for `revolute`/`continuous`/`prismatic`/`fixed`.
- ☑ `model/edit_ops.py` — `EditOperation` types + `apply()` for each operation.
- ☑ `model/version_store.py` — immutable versions + rollback.
- ☑ `model_update_coordinator_node` — stage → validate → apply/reject.
- ☑ Unit tests + golden-model tests (known-good / known-broken URDFs → expected `ValidationResult`).

**Done when:** a scripted sequence of edits stages, validates, applies, and rolls back correctly, all under unit + golden tests, with zero AI involvement. ✅ Met: `RobotModel` parses/serializes plain URDF; the `schema`/`topology`/`joint_rules` checks compose in `validation/engine.py` into a single `ValidationResult`; `model/edit_ops.py` and `model/version_store.py` back a `ModelUpdateCoordinator` that stages, validates, applies, and rolls back; and the golden good/broken URDFs under `src/urdf_live_editor/test/models/` lock the verdicts.

---

## Milestone 2 — Live visualization

**Goal:** edits are visible in RViz2 in real time.

- ☑ `joint_state_adapter_node` — clamp bounded joints, wrap continuous joints, publish `/joint_states`.
- ☑ Republish `robot_description`; wire `robot_state_publisher` + RViz2.
- ☑ `launch/live_editor.launch.py` brings up the full deterministic stack.
- ☑ `launch_testing` integration tests asserting on published TF.

**Done when:** editing the sample robot's joints updates the RViz2 model live, verified by an automated launch test. ✅ Met: `JointStateAdapter` (the offline-testable core of `joint_state_adapter_node`) clamps `revolute`/`prismatic` commands to their limits and wraps `continuous` joints into `(-pi, pi]`, carrying positions across live model edits; `live_editor.launch.py` wires `urdf_source_node` → `robot_state_publisher` (+ optional RViz2 with a packaged config) alongside the adapter; and `test/test_live_editor_launch.py` (a `launch_testing` test) brings the stack up headless, asserts the sample arm's moving links appear on `/tf`, and drives `/joint_commands` to confirm a shoulder command rotates `link_1`. Adapter clamp/wrap logic is additionally locked by offline unit tests in `test/test_joint_state_adapter.py`.

---

## Milestone 3 — Web API

**Goal:** the pipeline is reachable over HTTP/WebSocket.

- ☐ `web_api_node` — REST for read / stage / validate / apply / rollback.
- ☐ WebSocket stream for live validation diagnostics and model events.
- ☐ API contract tests.

**Done when:** the same edit flow available on the ROS side is fully drivable through the API and covered by contract tests.

---

## Milestone 4 — Claude Agent SDK layer

**Goal:** natural-language editing, repair, and explanation on top of the trusted core.

- ☐ MCP tools: `read_urdf`, `stage_edit`, `validate_model`, `apply_model`, `rollback`, `describe_joint`.
- ☐ Hooks: pre-tool (mutations must target a staged candidate), post-tool (audit log with diff).
- ☐ **URDF Editor Agent** — natural language → `EditOperation` JSON.
- ☐ **Constraint Validator Agent** + **Kinematic Reasoning Agent** — human-readable explanations of failures and degeneracies.
- ☐ **Repair Agent** — fix malformed URDF, propose `suggested_repairs`.
- ☐ Recorded-response tests so the AI layer runs deterministically in CI; opt-in live-SDK suite.

**Done when:** a user instruction like "add a ±90° elbow between link_2 and link_3" produces a validated, applied edit, and a broken URDF can be diagnosed and repaired — all reproducible in CI without live API calls.

---

## Milestone 5 — UX & robustness

- ☐ Optional web front-end (`web/`) for editing + visualization.
- ☐ **Launch/Integration Agent** to keep launch/config in sync after changes.
- ☐ Structured logging, diagnostics, and an audit-trail viewer.
- ☐ Documentation site under `docs/` (architecture + tutorials).

---

## Milestone 6 — Extensions (stretch)

- ☐ `ros2_control` integration (controllers over edited joints).
- ☐ Gazebo simulation of the live-edited model.
- ☐ Multi-robot / multi-model sessions.
- ☐ Collision-geometry and inertial validation.

---

## Immediate next steps

The following are the concrete tasks to pick up first, in order:

1. ☑ Scaffold the `colcon` workspace with the two packages and make `colcon build` pass (Milestone 0).
2. ☑ Add a minimal `sample_arm.urdf.xacro` and a `pytest` that just parses it (locks in the test harness).
3. ☑ Set up CI (build + lint + test).
4. ☑ Implement `schema.py` and `joint_rules.py` with unit tests — the smallest useful slice of the deterministic core (Milestone 1).
5. ☑ Wire the deterministic stack into RViz2 with a live joint-state adapter (Milestone 2).
6. ☐ Expose the pipeline over HTTP/WebSocket via `web_api_node` (Milestone 3).

Milestone 1 is complete: the deterministic core — model, validation engine,
edit operations, version store, and the stage → validate → apply/reject
coordinator — is implemented and covered by unit and golden-model tests, all
runnable offline with zero AI involvement.

Milestone 2 is complete: `joint_state_adapter_node` clamps bounded joints and
wraps continuous joints into `/joint_states`; `live_editor.launch.py` brings up
the full deterministic stack (`urdf_source_node` → `robot_state_publisher` +
adapter, with optional RViz2); and a `launch_testing` integration test asserts
the sample arm's TF appears and that a joint command moves it. Editing the
sample robot now updates the RViz2 model live. The next slice is the web API
(Milestone 3).

---

_Last updated: 2026-07-22._
