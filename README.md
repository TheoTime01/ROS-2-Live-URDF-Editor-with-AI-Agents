# ROS 2 Live URDF Editor with AI Agents

A production-oriented ROS 2 project for **live editing, validation, and visualization** of URDF/Xacro robot models with AI-assisted editing workflows.

This project is designed to let users modify robot structure and joint definitions in real time while enforcing kinematic constraints for `revolute`, `continuous`, `prismatic`, and `fixed` joints. In ROS 2, `joint_state_publisher` publishes `sensor_msgs/msg/JointState` data from a URDF or `robot_description`, while `robot_state_publisher` uses the robot description together with joint states to publish the robot transform tree.

The AI subsystem is intended to run on the **Claude Agent SDK**, which Anthropic documents as a programmable agent framework for Python and TypeScript that includes the same agent loop, tool access, and context management used by Claude Code.

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


## Live update flow

Every edit follows a staged update pipeline so the running model remains stable even when a user submits invalid changes.

1. A user edits the URDF/Xacro file or sends a natural-language instruction.
2. The Claude-powered editor agent converts the request into structured `EditOperation` JSON.
3. A staged candidate model is created.
4. Deterministic validation and AI-assisted validation both run.
5. If valid, the system republishes `robot_description`, refreshes downstream state, and stores a new version.
6. If invalid, the change is rejected and the user receives diagnostics plus repair suggestions.

## Installation


## Claude Agent SDK integration


## Validation policy



## AI agent behavior


### Recommended JSON outputs

### Example user instructions

## Testing

## Roadmap

## Troubleshooting

### Robot does not move in RViz

### Joint edits are rejected

### Continuous joint behaves like a bounded joint

### Claude agent cannot run
