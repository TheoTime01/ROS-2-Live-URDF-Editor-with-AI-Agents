# Extensions (Milestone 6)

Milestone 6 extends the trusted core beyond a single visualized model. Four
deterministic, ROS-independent modules live under
`urdf_live_editor.extensions`, all sharing the small report primitives in
`extensions.report` (`Severity` / `Issue` / `Report`). Like the rest of the
project, they are fully unit-testable offline: an agent can explain their output
but can never fabricate a passing result.

| Module | What it does |
|---|---|
| `extensions.ros2_control` | Generate `<ros2_control>` + controller YAML; validate a controllers config |
| `extensions.gazebo` | Generate `gazebo_ros2_control` wiring + a spawn plan; check sim readiness |
| `extensions.sessions` | Multi-model sessions, URDF namespacing, frame-collision detection |
| `extensions.physical_validation` | Mass / inertia / collision-geometry plausibility |

## Report primitives

Every extension validator returns a `Report`:

```python
report.ok            # True when there are no ERROR issues (warnings are allowed)
report.clean         # True when there are no issues at all
report.errors()      # [Issue, ...] at ERROR
report.warnings()    # [Issue, ...] at WARNING
report.of_code("mass_nonpositive")   # match on the stable machine code
report.worst()       # Severity.INFO | WARNING | ERROR
report.to_dict()     # JSON-ready, suitable for the web UI or audit trail
```

## `ros2_control` integration

Generate both artifacts `ros2_control` needs directly from the model's movable
joints, so they can never drift from it:

```python
from urdf_live_editor.extensions.ros2_control import (
    generate_ros2_control_xml, embed_ros2_control,
    generate_controller_manager_yaml, validate_controllers_config,
)

block = generate_ros2_control_xml(urdf_xml, name="ArmSystem")
urdf_with_control = embed_ros2_control(urdf_xml, block)   # input never mutated

controllers = generate_controller_manager_yaml(urdf_xml, update_rate=100)
```

Interface conventions: `revolute` / `prismatic` joints get a `position` command
interface; `continuous` joints get a `velocity` command interface (no position
limit to command against). Both expose `position` + `velocity` state interfaces.
`fixed` joints are never given interfaces. A model containing any
velocity-command joint yields a `JointGroupVelocityController`; otherwise a
`JointTrajectoryController`.

Validate a hand-written controllers config against the model:

```python
report = validate_controllers_config(urdf_xml, controllers)
```

| Code | Severity | Meaning |
|---|---|---|
| `joint_not_in_model` | ERROR | a controller owns a joint the model does not have |
| `joint_not_movable` | ERROR | a controller owns a `fixed` joint (no runtime DOF) |
| `joint_double_owned` | ERROR | two controllers own the same joint (interface contention) |
| `joint_uncontrolled` | WARNING | a movable joint is owned by no controller |

## Gazebo simulation

```python
from urdf_live_editor.extensions.gazebo import (
    generate_gazebo_ros2_control_block, build_spawn_plan, check_gazebo_readiness,
)

gz = generate_gazebo_ros2_control_block(
    controllers_path="config/controllers.yaml", parameters_package="my_pkg")

plan = build_spawn_plan(entity_name="arm", controllers=["arm_controller"],
                        namespace="robot_a")
plan.to_dict()   # ordered steps: gazebo -> robot_state_publisher -> spawn_entity -> spawners
```

The spawn plan encodes Gazebo's hard ordering constraints:
`robot_state_publisher` must publish `robot_description` before `spawn_entity`
reads it, the entity must exist before any controller spawner runs, and
`joint_state_broadcaster` is always started first.

`check_gazebo_readiness(urdf_xml)` is a stricter reading of the physical report:
a link with no inertial is an **error** (`gazebo_inertial_missing` — Gazebo drops
massless links), and a mass-bearing link with no collision is a **warning**
(`gazebo_collision_missing` — objects pass through it).

## Multi-model sessions

Run several models side by side without name, namespace, or TF collisions:

```python
from urdf_live_editor.extensions.sessions import (
    SessionRegistry, ModelSession, namespace_urdf,
)

reg = SessionRegistry()
reg.add(ModelSession("left",  "arm1", urdf_left))
reg.add(ModelSession("right", "arm2", urdf_right))
# add() raises DuplicateSessionError on a repeated id or namespace

reg.combined_frames()   # ['arm1_base_link', 'arm1_tip', 'arm2_base_link', ...]
reg.check_scene()       # frame_collision errors, or scene_ok
```

`namespace_urdf(urdf, "arm1")` rewrites every link/joint name and every
`parent` / `child` / `mimic` reference to a prefixed form, producing a model that
can join a shared TF tree with no clashes.

## Collision & inertial validation

```python
from urdf_live_editor.extensions.physical_validation import validate_physical

report = validate_physical(urdf_xml, require_collision=True)
```

| Code | Severity | Meaning |
|---|---|---|
| `mass_missing` / `mass_nonpositive` | ERROR | inertial with no / non-positive mass |
| `inertia_zero` | ERROR | an all-zero inertia tensor placeholder |
| `inertia_incomplete` | ERROR | one or more inertia components missing |
| `inertia_not_spd` | ERROR | inertia tensor is not positive-definite |
| `inertia_triangle_inequality` | WARNING | principal moments violate `I1 + I2 ≥ I3` |
| `geometry_nonpositive` | ERROR | a box/cylinder/sphere/mesh dimension `≤ 0` |
| `inertial_missing` | WARNING | a joint-child link has no inertial |
| `collision_missing` | INFO (ERROR with `require_collision`) | mass but no collision geometry |

The positive-definiteness test uses Sylvester's criterion with scale-relative
thresholds (robust for both large and very small tensors), and the triangle
inequality is checked against principal moments computed with a **closed-form**
symmetric-3×3 eigensolver — so this module needs no NumPy or SciPy and stays
importable in the same minimal environment as the rest of the core.

A simulation-ready sample model that passes every check lives at
`models/sample_arm/sample_arm_sim.urdf`.

## Why deterministic-first

These extensions produce launch/controller/simulation artifacts and physical
verdicts in deterministic code. That is what lets the AI layer stay a
convenience: it can generate a `ros2_control` block, draft a controllers file, or
explain why a link is unsimulatable, but it cannot ship an interface the model
does not support or call a physically-impossible model valid.
