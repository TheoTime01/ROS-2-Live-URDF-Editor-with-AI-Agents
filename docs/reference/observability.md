# Observability

`urdf_live_editor.observability` provides three deterministic, ROS-independent
building blocks used across the stack and surfaced in the web UI's diagnostics
and audit-trail views. All three are unit-tested offline; the ROS and web
bridges are thin wrappers.

## Structured logging

One event is one JSON object is one line (JSONL). A logger carries **bound
context** that is merged into every event it emits.

```python
from urdf_live_editor.observability import get_logger, configure, LogLevel

configure(level=LogLevel.INFO)                 # process-wide threshold
log = get_logger("web_api", node="web_api_node")

req = log.bind(request_id="r-42", session="s1")
req.info("stage_received", operations=2)
req.warning("slow_validation", ms=920)
```

Every record has a stable schema:

```json
{"ts": 1721700000.5, "level": "INFO", "logger": "web_api",
 "event": "stage_received", "fields": {"node": "web_api_node",
 "request_id": "r-42", "session": "s1", "operations": 2}}
```

- **Sinks** receive fully-formed records. A JSONL stderr sink ships by default;
  register an in-memory sink to stream logs to the browser, or a file sink for
  persistence.
- Values that are not JSON-serializable fall back to `repr` — a logging call
  never raises.
- A broken sink can never crash the caller.

!!! tip "ROS bridge"
    Inside an `rclpy` node, wrap `StructuredLogger` so `log.info(...)` also calls
    the node's `get_logger().info(...)`. Levels map 1:1
    (`DEBUG=10 … FATAL=50`).

## Diagnostics

`Diagnostics` aggregates per-subsystem health into an immutable snapshot. Levels
mirror `diagnostic_msgs/DiagnosticStatus`: `OK=0`, `WARN=1`, `ERROR=2`,
`STALE=3`.

```python
from urdf_live_editor.observability import Diagnostics

diag = Diagnostics()
diag.ok("validation", "12 checks passed", checks=12)
diag.warn("web_api", "high latency", p99_ms=900)
diag.heartbeat("urdf_source", stale_after=5.0)   # call on a timer

report = diag.snapshot()
report.overall        # DiagnosticLevel.WARN  (worst across components)
report.healthy()      # False
report.to_dict()      # JSON for GET /api/diagnostics and the dashboard
```

- `heartbeat(name, stale_after=...)` proves liveness; if no update arrives within
  `stale_after` seconds, the component is reported as `STALE` automatically.
- `snapshot()` orders components worst-first, then by name, for a stable
  dashboard.

## Audit trail

`AuditTrail` is an append-only, **hash-chained** log of applied model changes —
the concrete form of the project's "everything is auditable" principle.

```python
from urdf_live_editor.observability import AuditTrail

trail = AuditTrail(path="audit/model_audit.jsonl")   # JSONL-backed, survives restart
entry = trail.record(
    actor="agent:editor",
    action="apply",
    summary="add revolute joint 'elbow'",
    from_version="v3", to_version="v4",
    operation={"operation": "add_joint", "target": {"name": "elbow"}},
    diff=["+ joint elbow (revolute)", "+ link link_3"],
    metadata={"session": "s1"},
)
```

Each entry records **who** (`actor`), **what** (`action` + `operation` + `diff`),
**when** (`ts`), and the resulting **version**. Entries are chained: every entry
stores the SHA-256 hash of the previous one plus a hash of its own payload.

```python
trail.query(actor="agent:editor", action="apply", text="elbow", limit=10)
trail.verify()      # [] means intact; otherwise a list of problems
trail.is_intact()   # True / False
```

Because the chain covers each entry's payload and its predecessor's hash, any
truncation or in-place edit is detectable — which is exactly what the web
audit-trail viewer's **Verify integrity** button checks.

!!! note "Two audit trails, one meaning"
    The browser mock backend keeps its own lightweight chained trail so the UI
    demonstrates tamper-evidence offline. The Python `AuditTrail` above is the
    authoritative, cryptographic (SHA-256) implementation used by the ROS stack.
