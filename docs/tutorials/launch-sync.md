# Keeping launch/config in sync

After you edit the model, files that *reference* joints can drift out of date —
most commonly the per-joint policy in `config/validation_policy.yaml`. This
tutorial uses the Launch/Integration Agent to detect and fix that drift. It is
pure Python; no API key is required.

## The scenario

You just added a `wrist` continuous joint to the sample arm, but
`validation_policy.yaml` still only lists `shoulder` and `elbow`.

```python
from urdf_live_editor.integration.launch_sync import extract_model_summary, load_yaml
from urdf_ai_agents.agents import LaunchIntegrationAgent

with open("models/sample_arm/sample_arm.urdf") as f:
    model = extract_model_summary(f.read())

config = load_yaml("src/urdf_live_editor/config/validation_policy.yaml")
```

## 1. Analyze

```python
agent = LaunchIntegrationAgent()
report = agent.analyze(model, {"validation_policy": config})

print("in sync?", report.in_sync)
print(agent.explain(report))
```

If `wrist` is missing you'll see:

```
[validation_policy]
  - add 'wrist': continuous joint present in model but absent from validation_policy
```

The planner also detects **stale** entries (a joint that no longer exists, or a
joint that became `fixed` and so has no runtime DOF) and **retypes** (a joint
whose type changed).

## 2. Check launch references too

```python
report = agent.analyze(
    model,
    {"validation_policy": config},
    launch_references={
        "model": "models/sample_arm/sample_arm.urdf",
        "rviz_config": "config/live.rviz",
    },
    base_dir=".",
)
for issue in report.reference_issues:
    print(issue.key, "->", issue.message)
```

Any reference that does not resolve on disk is reported — e.g. an RViz config the
launch file points at but that was renamed.

## 3. Apply the fix

```python
plan = report.plans[0]
if not plan.in_sync:
    updated = agent.apply_plan(config, model, plan, model_version="v4")
    # `updated` is a new dict, in sync with the model. Write it back:
    import yaml
    with open("src/urdf_live_editor/config/validation_policy.yaml", "w") as f:
        yaml.safe_dump(updated, f, sort_keys=False)
```

`apply_plan` records a structured log event and, if the agent was constructed
with an `AuditTrail`, an audit entry — so the config change is traceable
alongside model changes.

## Why the agent can't go rogue

The **decision** about what to change is made entirely by the deterministic
planner (`plan_config_sync`). The agent only explains that plan and applies the
exact actions it lists. Even with the Claude Agent SDK wired in for richer
explanations, it cannot introduce a change the planner did not produce — the same
guarantee that protects the model itself.

## Automating it

Wire `analyze` into your post-apply hook (Milestone 4) so that immediately after
any model change the agent reports drift, and optionally opens a fix. Combined
with the [audit trail](../reference/observability.md#audit-trail), you get a full
record of both model and configuration evolution.
