# Getting started

This tutorial gets the deterministic core, the observability layer, and the web
UI running on your machine. None of it requires an Anthropic API key — the AI
layer is optional and layered on top.

## Prerequisites

- ROS 2 Humble (or newer LTS) installed and sourced — required for the full ROS
  stack (Milestones 1–3). The Milestone 5 Python modules and the web UI run
  without ROS.
- Python 3.10+.
- Node 18+ (only to run the web front-end's unit tests).

## Clone and build

```bash
git clone https://github.com/theotime01/ros-2-live-urdf-editor-with-ai-agents.git
cd ros-2-live-urdf-editor-with-ai-agents

# Full ROS build (when ROS 2 is sourced):
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
```

## Run the deterministic Python tests

The observability and launch-sync modules are pure Python and testable without
ROS:

```bash
python3 -m pytest src/urdf_live_editor/test -q
python3 -m pytest src/urdf_ai_agents/test -q      # needs both packages importable
```

If you are not using a colcon install, put both packages on the path:

```bash
export PYTHONPATH=src/urdf_live_editor:src/urdf_ai_agents
```

## Launch the live editor (ROS)

```bash
ros2 launch urdf_live_editor live_editor.launch.py \
  model:=models/sample_arm/sample_arm.urdf
```

This brings up the source node, validator, joint-state adapter,
`robot_state_publisher`, and RViz2. Editing the model — from a file change, the
web UI, or an agent — updates RViz2 live.

## Start the web UI

```bash
cd web
python3 server.py           # http://127.0.0.1:8080
npm test                    # optional: run the front-end unit tests
```

With no ROS backend running, the UI uses its in-browser mock backend, so you can
explore the whole edit → validate → apply → rollback flow offline. To connect it
to a running `web_api_node`, open `http://127.0.0.1:8080/?api=http://localhost:8000`.

## Next steps

- [Make your first live edit](first-edit.md)
- [Tour the web UI](web-ui.md)
- [Keep launch/config in sync](launch-sync.md)
