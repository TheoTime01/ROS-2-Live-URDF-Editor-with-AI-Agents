# Launch/Integration sync

When the robot model changes — a joint is added, removed, renamed, or retyped —
several *non-model* artifacts must be kept in step with it:

- per-joint policy/config files that enumerate joints
  (e.g. `config/validation_policy.yaml`),
- launch-file references to the model, the RViz config, and controller configs,
- any joint list a GUI or controller manager consumes.

The **deterministic planner** in
`urdf_live_editor.integration.launch_sync` computes exactly what must change; the
**Launch/Integration Agent** in
`urdf_ai_agents.agents.launch_integration_agent` is a thin wrapper that explains
and, on request, applies that plan. The agent can never invent a change the
planner did not authorize.

## Deterministic planner

### Extract a model summary

```python
from urdf_live_editor.integration.launch_sync import extract_model_summary

model = extract_model_summary(urdf_xml)   # already Xacro-expanded XML
model.movable_joints                      # {name: JointInfo} for revolute/continuous/prismatic
model.joint_names(movable_only=True)      # sorted names
```

### Plan the config sync

```python
from urdf_live_editor.integration.launch_sync import plan_config_sync

config = {"joints": {"shoulder": {"type": "revolute"},
                     "elbow": {"type": "revolute"}}}   # wrist is missing
plan = plan_config_sync(model, config, config_name="validation_policy")

plan.in_sync           # False
plan.summary()         # "validation_policy: 1 add"
plan.to_dict()         # JSON-ready, suitable for the audit trail
```

A plan is a list of `SyncAction`s, each with a `ChangeKind`:

| Kind | Meaning |
|---|---|
| `add` | joint exists in the model but not in the config |
| `remove` | config entry has no matching (movable) joint — stale |
| `retype` | the joint's type changed; the config's `type` must be updated |

By default only **movable** joints are expected in the config, since `fixed`
joints carry no runtime DOF; a `fixed` joint still listed in the config is
flagged for removal.

### Apply the plan

```python
from urdf_live_editor.integration.launch_sync import apply_config_sync

updated = apply_config_sync(config, model, plan, default_entry={"clamp": True})
# updated is a NEW dict; the input is never mutated.
# New joints get {"type": <joint_type>, ...default_entry}; retypes update
# `type` in place while preserving operator-set keys; stale entries are dropped.
```

### Check launch references

```python
from urdf_live_editor.integration.launch_sync import check_launch_references

issues = check_launch_references(
    {"model": "models/sample_arm/sample_arm.urdf",
     "rviz_config": "config/live.rviz"},
    base_dir=".",
)
# -> one ReferenceIssue per path that does not resolve on disk
```

## The agent wrapper

```python
from urdf_ai_agents.agents import LaunchIntegrationAgent
from urdf_live_editor.observability import AuditTrail

agent = LaunchIntegrationAgent(audit_trail=AuditTrail(path="audit/model_audit.jsonl"))

report = agent.analyze_urdf(
    urdf_xml,
    configs={"validation_policy": config},
    launch_references={"rviz_config": "config/live.rviz"},
)

print(agent.explain(report))     # human-readable drift explanation
if not report.in_sync:
    updated = agent.apply_plan(config, model, report.plans[0], model_version="v4")
    # apply_plan records a structured log event and an audit entry.
```

`explain()` uses a deterministic renderer that is always the ground truth. When
the Claude Agent SDK and an API key are configured, the agent can additionally
produce richer natural-language prose using its focused system prompt — but the
deterministic plan remains authoritative.

## Why deterministic-first

Keeping the *decision* about what to change in deterministic code (and the audit
record of every applied change) is what lets the AI layer stay a convenience: it
can describe drift and draft a fix, but it cannot silently change your launch or
config in a way the planner would not have produced.
