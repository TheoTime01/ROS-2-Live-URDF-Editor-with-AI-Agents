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
- ☐ Two-package `colcon` workspace: `urdf_live_editor` (deterministic) and `urdf_ai_agents` (Claude Agent SDK).
- ☐ `package.xml` / `setup.py` for both packages; `colcon build` succeeds.
- ☐ CI pipeline: `colcon build`, lint (`ament_flake8`, `ament_pep257`), and `pytest` on every push.
- ☐ Sample robot under `models/sample_arm/` used by demos and tests.

**Done when:** `colcon build && colcon test` passes green in CI on an empty-but-wired skeleton.

---

## Milestone 1 — Deterministic core (no AI)

**Goal:** the constraint engine and staged-edit pipeline exist and are trusted.

- ☐ `urdf_source_node` — load + hot-reload URDF/Xacro from disk (file watcher).
- ☐ Validation engine (`validation/`):
  - ☐ `schema.py` — well-formedness, unique names, parent/child references.
  - ☐ `topology.py` — single connected tree, one root, no cycles/orphans.
  - ☐ `joint_rules.py` — per-type rules for `revolute`/`continuous`/`prismatic`/`fixed`.
- ☐ `model/edit_ops.py` — `EditOperation` types + `apply()` for each operation.
- ☐ `model/version_store.py` — immutable versions + rollback.
- ☐ `model_update_coordinator_node` — stage → validate → apply/reject.
- ☐ Unit tests + golden-model tests (known-good / known-broken URDFs → expected `ValidationResult`).

**Done when:** a scripted sequence of edits stages, validates, applies, and rolls back correctly, all under unit + golden tests, with zero AI involvement.

---

## Milestone 2 — Live visualization

**Goal:** edits are visible in RViz2 in real time.

- ☐ `joint_state_adapter_node` — clamp bounded joints, wrap continuous joints, publish `/joint_states`.
- ☐ Republish `robot_description`; wire `robot_state_publisher` + RViz2.
- ☐ `launch/live_editor.launch.py` brings up the full deterministic stack.
- ☐ `launch_testing` integration tests asserting on published TF.

**Done when:** editing the sample robot's joints updates the RViz2 model live, verified by an automated launch test.

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

**Goal:** make the system usable and robust for real work — a UI, observability,
config-drift protection, and documentation.

- ☑ Optional web front-end (`web/`) for editing + visualization — no-build ES
  modules with an offline mock backend, kinematic-tree visualization, and an
  audit-trail viewer. Pure modules covered by `node --test`; an optional
  Playwright end-to-end smoke test drives the real page.
- ☑ **Launch/Integration Agent** to keep launch/config in sync after changes —
  a deterministic planner (`urdf_live_editor/integration/launch_sync.py`) plus a
  thin agent wrapper (`urdf_ai_agents/.../launch_integration_agent.py`) that can
  never invent a change the planner did not authorize.
- ☑ Structured logging, diagnostics, and an audit-trail viewer —
  `urdf_live_editor/observability/` (JSONL logging, OK/WARN/ERROR/STALE
  diagnostics, hash-chained audit trail), surfaced in the web UI.
- ☑ Documentation site under `docs/` (architecture + tutorials) — MkDocs +
  Material, builds green with `mkdocs build --strict`.

**Done when:** the web UI drives the full edit → validate → apply → rollback flow
(offline or against the ROS API), every applied change is logged and auditable,
config drift is detected and repairable, and the docs site builds — all covered
by `pytest`, `node --test`, and a build check. **✅ Met.**

---

## Milestone 6 — Extensions (stretch)

**Goal:** extend the trusted core beyond a single visualized model — drive edited
joints with real controllers, simulate the model, run several models at once, and
validate the physics — all as deterministic, offline-testable modules under
`urdf_live_editor/extensions/`, following the same "AI can explain but never
bypass" contract as the earlier milestones.

- ☑ `ros2_control` integration (controllers over edited joints) —
  `extensions/ros2_control.py` deterministically generates the `<ros2_control>`
  URDF block and controller-manager YAML from the model's movable joints, and
  validates a hand-written controllers config against the model (joint-not-in-
  model, joint-not-movable, uncontrolled, and double-owned findings).
- ☑ Gazebo simulation of the live-edited model — `extensions/gazebo.py`
  generates the `gazebo_ros2_control` plugin block and an ordered, deterministic
  spawn plan (RViz/RSP → `spawn_entity` → controller spawners), and reports
  simulation readiness (massless links Gazebo would drop, collision-free links
  objects pass through).
- ☑ Multi-robot / multi-model sessions — `extensions/sessions.py` provides a
  `SessionRegistry` enforcing unique namespaces, deterministic URDF namespacing
  (links, joints, parent/child and `mimic` references), and combined-scene
  frame-collision detection.
- ☑ Collision-geometry and inertial validation — `extensions/physical_validation.py`
  checks mass positivity, positive-definite inertia tensors (dependency-free
  Sylvester + closed-form symmetric-3×3 eigenvalues), the principal-moment
  triangle inequality, and non-positive geometry dimensions.

All four share the small `extensions/report.py` primitives (`Severity` / `Issue`
/ `Report`) and are covered by `pytest`. A simulation-ready sample model lives at
`models/sample_arm/sample_arm_sim.urdf`.

**Done when:** the model's controllers, simulation artifacts, multi-model
namespacing, and physical plausibility can all be generated and validated
deterministically offline, covered by `pytest`, with no ROS, Gazebo, or LLM
dependency at test time. **✅ Met.**

---

## Immediate next steps

The following are the concrete tasks to pick up first, in order:

1. Scaffold the `colcon` workspace with the two packages and make `colcon build` pass (Milestone 0).
2. Add a minimal `sample_arm.urdf.xacro` and a `pytest` that just parses it (locks in the test harness).
3. Set up CI (build + lint + test).
4. Implement `schema.py` and `joint_rules.py` with unit tests — the smallest useful slice of the deterministic core.

---

_Last updated: 2026-07-23._
