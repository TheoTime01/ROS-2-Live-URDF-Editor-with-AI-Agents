# ROS 2 Live URDF Editor with AI Agents

A production-oriented ROS 2 project for **live editing, validation, and visualization** of URDF/Xacro robot models with AI-assisted editing workflows.

This project is designed to let users modify robot structure and joint definitions in real time while enforcing kinematic constraints for `revolute`, `continuous`, `prismatic`, and `fixed` joints. In ROS 2, `joint_state_publisher` publishes `sensor_msgs/msg/JointState` data from a URDF or `robot_description`, while `robot_state_publisher` uses the robot description together with joint states to publish the robot transform tree.

The AI subsystem is intended to run on the **Claude Agent SDK**, which Anthropic documents as a programmable agent framework for Python and TypeScript that includes the same agent loop, tool access, and context management used by Claude Code.

> **Project status:** early design / scaffolding stage. This README describes the intended architecture and the roadmap that drives implementation. Sections that describe commands or code refer to the planned package layout; see the [Roadmap](#roadmap) for what is implemented versus planned.

## Features

- Live URDF/Xacro editing through file watching, API calls, and optional web UI.
- Constraint-aware validation for `revolute`, `continuous`, `prismatic`, and `fixed` joints based on URDF semantics.
- Safe staging of edits before applying them to the active robot model.
- Real-time robot visualization with RViz2 and TF updates through `robot_state_publisher`.
- AI-agent-assisted editing, repair, validation, and reasoning powered by the Claude Agent SDK.
- Rollback/versioning support for model changes.
- Modular ROS 2 package layout for future extensions such as `ros2_control` and Gazebo integration.

## Architecture

The system is split into deterministic robotics components and AI-assisted reasoning components so invalid edits never directly mutate the active model. ROS documentation states that the movable robot workflow relies on non-fixed joints and their limits, which makes a dedicated constraint engine essential for safe live updates.

### Core components

- `urdf_source_node`: Loads and reloads URDF/Xacro files.
- `constraint_validation_node`: Parses the model and validates kinematic rules.
- `joint_state_adapter_node`: Maintains runtime joint values, clamps bounded joints, and wraps continuous joints.
- `model_update_coordinator_node`: Stages, validates, applies, and rolls back model versions.
- `ai_agent_node`: Accepts natural-language edit instructions and converts them into structured edit operations.
- `web_api_node`: Exposes REST/WebSocket endpoints for editing, validation, and diagnostics.

### AI runtime

The AI layer should use the Claude Agent SDK Python package, which Anthropic documents as installable with `pip install claude-agent-sdk` or `uv add claude-agent-sdk` and compatible with Python 3.10 or later.

Recommended reasons to use it here:

- Built-in tool execution for reading files, editing code, running shell commands, and fetching web content.
- Support for hooks, so file changes, validation gates, and audit events can be intercepted around tool usage.
- Support for subagents, which fits the architecture of editor, validator, reasoner, and repair agents.
- Support for MCP servers, which can expose custom robotics tools or external integrations.
- Session management, which is useful for continuing multi-step repair or modeling workflows.

### AI agents

- **URDF Editor Agent**: Turns natural-language requests into structured edits.
- **Constraint Validator Agent**: Explains semantic or kinematic violations.
- **Kinematic Reasoning Agent**: Detects chain, axis, and topology problems.
- **Repair Agent**: Repairs malformed XML/URDF and suggests safe fixes.
- **Launch/Integration Agent**: Helps maintain launch/config integration after project changes.

## Supported joint semantics

The project enforces the following joint behaviors derived from ROS URDF conventions.

| Joint type | Motion | Validation behavior |
|---|---|---|
| `revolute` | Bounded rotation | Requires axis and lower/upper limits; current values are clamped to range.|
| `continuous` | Unbounded rotation | Requires axis; no finite angular bounds are required. |
| `prismatic` | Bounded translation | Requires axis and lower/upper limits; values are clamped in meters.|
| `fixed` | No motion | No runtime DOF exposed; joint remains static in the TF tree.|

## Workspace layout

The project is organized as a standard ROS 2 (`colcon`) workspace. The AI layer lives inside the same repository so agents can operate directly on the robotics packages.

```
ROS-2-Live-URDF-Editor-with-AI-Agents/
├── README.md
├── .gitignore
├── src/
│   ├── urdf_live_editor/                # Core ROS 2 package (Python, ament_python)
│   │   ├── package.xml
│   │   ├── setup.py
│   │   ├── setup.cfg
│   │   ├── resource/
│   │   ├── urdf_live_editor/
│   │   │   ├── __init__.py
│   │   │   ├── urdf_source_node.py
│   │   │   ├── constraint_validation_node.py
│   │   │   ├── joint_state_adapter_node.py
│   │   │   ├── model_update_coordinator_node.py
│   │   │   ├── web_api_node.py
│   │   │   ├── validation/               # Deterministic constraint engine
│   │   │   │   ├── joint_rules.py
│   │   │   │   ├── topology.py
│   │   │   │   └── schema.py
│   │   │   └── model/                    # EditOperation + version store
│   │   │       ├── edit_ops.py
│   │   │       └── version_store.py
│   │   ├── launch/
│   │   │   └── live_editor.launch.py
│   │   ├── config/
│   │   │   └── validation_policy.yaml
│   │   └── test/
│   │       ├── test_joint_rules.py
│   │       ├── test_edit_ops.py
│   │       └── test_version_store.py
│   │
│   └── urdf_ai_agents/                   # Claude Agent SDK layer (Python)
│       ├── package.xml
│       ├── setup.py
│       ├── urdf_ai_agents/
│       │   ├── ai_agent_node.py
│       │   ├── agents/                   # Editor / Validator / Reasoner / Repair / Launch
│       │   ├── tools/                    # MCP tools exposing robotics operations
│       │   └── prompts/
│       └── test/
│
├── models/                               # Sample URDF/Xacro robots for demos and tests
│   └── sample_arm/
│       └── sample_arm.urdf.xacro
├── web/                                  # Optional front-end for the web UI (later phase)
└── docs/
    └── architecture.md
```

Two packages keep a hard boundary: `urdf_live_editor` is deterministic robotics code with no dependency on any LLM, and `urdf_ai_agents` calls into it only through the same staged-edit and validation interfaces a human uses. This guarantees the AI cannot bypass validation.

## Live update flow

Every edit follows a staged update pipeline so the running model remains stable even when a user submits invalid changes.

1. A user edits the URDF/Xacro file or sends a natural-language instruction.
2. The Claude-powered editor agent converts the request into structured `EditOperation` JSON.
3. A staged candidate model is created.
4. Deterministic validation and AI-assisted validation both run.
5. If valid, the system republishes `robot_description`, refreshes downstream state, and stores a new version.
6. If invalid, the change is rejected and the user receives diagnostics plus repair suggestions.

## Installation

### Prerequisites

- ROS 2 Humble (or newer LTS) installed and sourced.
- Python 3.10+ (required by both ROS 2 and the Claude Agent SDK).
- `colcon` and `rosdep`.
- An Anthropic API key exported as `ANTHROPIC_API_KEY` for the AI layer.

### Build the workspace

```bash
# Clone into a workspace
git clone https://github.com/theotime01/ros-2-live-urdf-editor-with-ai-agents.git
cd ros-2-live-urdf-editor-with-ai-agents

# Install ROS dependencies
rosdep install --from-paths src --ignore-src -r -y

# Install Python dependencies for the AI layer
pip install claude-agent-sdk          # or: uv add claude-agent-sdk

# Build and source
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
```

### Run the live editor

```bash
# Launch the deterministic robotics stack (source node, validator, adapters, RViz2)
ros2 launch urdf_live_editor live_editor.launch.py model:=models/sample_arm/sample_arm.urdf.xacro

# In a second terminal, start the AI agent node
export ANTHROPIC_API_KEY=sk-ant-...
ros2 run urdf_ai_agents ai_agent_node
```

> Commands above reflect the planned package layout. Track implementation progress in the [Roadmap](#roadmap).

## Claude Agent SDK integration

The AI layer is a thin, auditable wrapper around the Claude Agent SDK. Agents never write the active `robot_description` directly — they only produce `EditOperation` JSON and call project tools that route through the same staged-validation pipeline a human uses.

- **Tools (MCP):** custom robotics tools are exposed to the agent, e.g. `read_urdf`, `stage_edit`, `validate_model`, `apply_model`, `rollback`, and `describe_joint`. Each tool is a deterministic function in `urdf_live_editor`.
- **Hooks:** pre-tool hooks enforce that any mutating operation targets a *staged* candidate, and post-tool hooks record an audit entry (who/what/when + resulting diff) for every applied change.
- **Subagents:** the Editor, Validator, Reasoner, Repair, and Launch/Integration agents are configured as subagents so each has a focused system prompt and tool scope.
- **Sessions:** multi-step repair or modeling conversations are kept in a session so the agent retains context across a workflow (e.g. "add a joint" → "it failed validation" → "fix it").
- **Model:** default to the latest capable Claude model; make the model id configurable via `config/validation_policy.yaml` or an environment variable.

Minimal usage sketch (Python):

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

options = ClaudeAgentOptions(
    system_prompt=EDITOR_SYSTEM_PROMPT,
    mcp_servers={"urdf": urdf_tools_server},   # exposes read_urdf/stage_edit/validate_model/...
    allowed_tools=["read_urdf", "stage_edit", "validate_model"],
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Add a revolute joint 'elbow' between link_2 and link_3, limits -1.57 to 1.57.")
    async for message in client.receive_response():
        handle(message)
```

## Validation policy

Validation runs in two independent passes on the **staged** candidate; a change is applied only if the deterministic pass succeeds. The AI pass never overrides the deterministic pass — it only adds explanations and repair suggestions.

### Deterministic checks (authoritative)

1. **XML/Xacro well-formedness** — the file parses and expands without error.
2. **Schema/structure** — every `link` and `joint` has a unique name; every joint references existing parent and child links.
3. **Topology** — the link/joint graph forms a single connected tree with exactly one root and no cycles; no orphan links.
4. **Per-joint rules** (see [Supported joint semantics](#supported-joint-semantics)):
   - `revolute` / `prismatic`: require `<axis>` and finite `<limit lower=... upper=...>` with `lower <= upper`; runtime values are clamped into range.
   - `continuous`: requires `<axis>`; must **not** require finite bounds; runtime values wrap.
   - `fixed`: exposes no DOF and must not carry a `<limit>` that implies motion.
5. **Units & ranges** — angular limits in radians, prismatic limits in meters; effort/velocity limits, if present, are non-negative.

### AI-assisted checks (advisory)

- Human-readable explanation of *why* a deterministic check failed.
- Detection of likely-unintended but technically valid changes (e.g. an axis that makes the chain kinematically degenerate).
- Suggested repairs returned as candidate `EditOperation`s, which themselves must pass deterministic validation before being applied.

Policy thresholds (which advisory checks are enabled, default limits, clamp behavior) live in `config/validation_policy.yaml`.

## AI agent behavior

Agents communicate with the system exclusively through structured JSON. Free-form prose is used only for explanations shown to the user, never for mutating the model.

### Recommended JSON outputs

**`EditOperation`** — the unit of change the Editor Agent emits:

```json
{
  "operation": "add_joint",
  "target": {
    "name": "elbow",
    "type": "revolute",
    "parent": "link_2",
    "child": "link_3",
    "axis": [0, 0, 1],
    "limit": { "lower": -1.57, "upper": 1.57, "effort": 10.0, "velocity": 1.0 },
    "origin": { "xyz": [0, 0, 0.4], "rpy": [0, 0, 0] }
  },
  "reason": "User requested an elbow joint between link_2 and link_3."
}
```

Supported `operation` values: `add_link`, `add_joint`, `update_joint`, `remove_joint`, `set_joint_limit`, `set_joint_axis`, `rename`.

**`ValidationResult`** — returned by the validation pass:

```json
{
  "valid": false,
  "errors": [
    {
      "code": "MISSING_LIMIT",
      "severity": "error",
      "joint": "elbow",
      "message": "revolute joint 'elbow' requires finite lower/upper limits."
    }
  ],
  "warnings": [],
  "suggested_repairs": [
    {
      "operation": "set_joint_limit",
      "target": { "name": "elbow", "limit": { "lower": -1.57, "upper": 1.57 } },
      "reason": "Add symmetric limits so the revolute joint is bounded."
    }
  ]
}
```

### Example user instructions

- "Add a continuous joint named `wheel_left` between `base_link` and `wheel_left_link` rotating about Y."
- "Change the elbow joint limits to ±90 degrees."
- "This URDF won't load in RViz — find and fix the error."
- "Convert `wrist` from fixed to revolute with a 30° range."
- "Remove `gripper_joint` and everything below it."

Each instruction is translated to one or more `EditOperation`s, staged, validated, and only then applied.

## Testing

Testing is layered so the deterministic core can be verified without any API access.

- **Unit tests (`pytest`)** for the validation engine (`joint_rules`, `topology`, `schema`), `EditOperation` application, and the version store. These run offline and gate every commit.
- **Integration tests** that launch the ROS 2 nodes with `launch_testing`, apply a sequence of staged edits, and assert on published `robot_description` and TF output.
- **Golden-model tests** that feed known-good and known-broken URDFs through validation and compare against expected `ValidationResult` JSON.
- **AI-layer tests** that stub or record Claude responses so agent behavior is tested deterministically in CI (no live API calls required); a separate opt-in suite exercises the live SDK.

```bash
# Deterministic core (no API key needed)
colcon test --packages-select urdf_live_editor
colcon test-result --verbose

# Or run the Python tests directly
pytest src/urdf_live_editor/test
```

## Roadmap

The roadmap is organized into milestones. Status legend: ☐ planned · ◐ in progress · ☑ done. See [`ROADMAP.md`](ROADMAP.md) for deliverables, acceptance criteria, and immediate next steps.

### Milestone 0 — Project scaffolding
- ☑ Repository, README, and `.gitignore`.
- ☑ Create the two-package `colcon` workspace (`urdf_live_editor`, `urdf_ai_agents`).
- ☑ CI: build + lint (`ament_flake8`, `ament_pep257`) + `pytest` on every push.
- ☑ Add a sample URDF/Xacro robot under `models/` for demos and tests.

### Milestone 1 — Deterministic core (no AI)
- ☐ `urdf_source_node`: load and hot-reload URDF/Xacro from disk.
- ☐ Validation engine: XML/Xacro well-formedness, schema, topology, per-joint rules.
- ☐ `EditOperation` model + `apply` semantics for all supported operations.
- ☐ Version store with rollback.
- ☐ `model_update_coordinator_node`: stage → validate → apply/reject pipeline.
- ☐ Unit tests + golden-model tests for the above.

### Milestone 2 — Live visualization
- ☐ `joint_state_adapter_node`: clamp bounded joints, wrap continuous joints.
- ☐ Republish `robot_description`; integrate `robot_state_publisher` and RViz2.
- ☐ `live_editor.launch.py` bringing up the full deterministic stack.
- ☐ `launch_testing` integration tests asserting on TF output.

### Milestone 3 — Web API
- ☐ `web_api_node`: REST endpoints for read/stage/validate/apply/rollback.
- ☐ WebSocket stream for live validation diagnostics and model events.
- ☐ API contract tests.

### Milestone 4 — Claude Agent SDK layer
- ☐ MCP tools exposing `read_urdf`, `stage_edit`, `validate_model`, `apply_model`, `rollback`, `describe_joint`.
- ☐ Pre/post tool hooks enforcing staged-only mutation + audit logging.
- ☐ URDF Editor Agent (natural language → `EditOperation`).
- ☐ Constraint Validator + Kinematic Reasoning agents (explanations).
- ☐ Repair Agent (fix malformed URDF, suggest safe repairs).
- ☐ Recorded-response tests so the AI layer runs deterministically in CI.

### Milestone 5 — UX & robustness
- ☐ Optional web front-end (`web/`) for editing and visualization.
- ☐ Launch/Integration Agent to keep launch/config in sync after changes.
- ☐ Diagnostics, structured logging, and audit trail viewer.
- ☐ Documentation site (`docs/`) with architecture and tutorials.

### Milestone 6 — Extensions (stretch)
- ☐ `ros2_control` integration (controllers over edited joints).
- ☐ Gazebo simulation of the live-edited model.
- ☐ Multi-robot / multi-model sessions.
- ☐ Collision-geometry and inertial validation.

## Troubleshooting

### Robot does not move in RViz

- Confirm `robot_state_publisher` and a joint-state source (`joint_state_publisher`, `joint_state_publisher_gui`, or `joint_state_adapter_node`) are running.
- In RViz2, set **Fixed Frame** to the robot's root link and add the **RobotModel** and **TF** displays.
- Check that the joint you expect to move is not `fixed` — fixed joints expose no DOF.
- Verify `/joint_states` is actually being published: `ros2 topic echo /joint_states`.

### Joint edits are rejected

- Read the `ValidationResult`: the `errors[].code` and `message` tell you exactly which rule failed.
- `revolute`/`prismatic` joints require an `<axis>` and finite `lower`/`upper` limits with `lower <= upper`.
- Ensure parent and child links exist and that the edit does not create a cycle or a second root.
- Apply a suggested repair from `suggested_repairs` — it must still pass deterministic validation.

### Continuous joint behaves like a bounded joint

- A `continuous` joint must not carry finite `<limit lower/upper>`; if it does, remove them or change the joint type.
- Confirm the adapter is **wrapping** the value rather than clamping it — clamping indicates the joint is being treated as `revolute`.

### Claude agent cannot run

- Export a valid key: `export ANTHROPIC_API_KEY=sk-ant-...`.
- Install the SDK: `pip install claude-agent-sdk` (Python 3.10+).
- Check outbound network access to the Anthropic API from the machine running `ai_agent_node`.
- If the agent runs but no edits apply, verify the MCP tools are registered and that hooks are not blocking a mutation that was never staged.
