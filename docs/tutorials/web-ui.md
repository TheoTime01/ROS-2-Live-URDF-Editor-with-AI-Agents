# The web UI

The web front-end (`web/`) is a dependency-free, no-build app for live editing,
visualization, and observability. This tutorial tours its panels and explains how
to run its tests.

## Layout

The screen has three columns:

### Edit (left)

- **URDF source** — a text editor for the raw URDF. **Stage source** parses and
  stages the whole document as a replacement candidate; **Reload current** pulls
  the active model back into the editor.
- **Quick edit operation** — a form that builds a single structured
  `EditOperation` (`add_joint`, `update_joint`, `set_joint_limit`,
  `set_joint_axis`, `remove_joint`, `rename`, `add_link`) and stages it.
- **Staged validation** — the `ValidationResult` for the current candidate, with
  clickable **suggested repairs**. **Apply staged** is enabled only when the
  candidate is valid; **Rollback** reverts to the previous version.

### Visualization (center)

A 2D kinematic-tree schematic of the model. Links are boxes; joints are labeled
edges colored by type (revolute, continuous, prismatic, fixed). The full RViz2
3D view is provided by the ROS stack — this is the browser preview.

### Observability (right)

Four tabs:

- **Audit trail** — every applied change (actor, action, summary, diff, version
  transition, and short hash), with free-text and action filters and a **Verify
  integrity** button that re-checks the hash chain.
- **Versions** — the immutable version history; each entry can roll back to that
  point.
- **Diagnostics** — per-subsystem health dots (`OK`/`WARN`/`ERROR`/`STALE`). In
  offline mode this shows representative subsystem state; against a real backend
  it reflects `GET /api/diagnostics`.
- **Logs** — a live JSONL stream of client-side pipeline events.

The header chips summarize connection mode, current version, validation status,
and overall health at a glance.

## Backends

The UI talks to a single client interface with two interchangeable backends:

- **Mock** — an in-browser reproduction of the staged-edit pipeline (used
  offline, for demos and tests).
- **HTTP** — REST + WebSocket to a real `web_api_node`.

`createClient()` probes the backend URL and falls back to the mock if it is
unreachable, so the app is always usable. Force a backend with the `?api=` query
parameter:

```
http://127.0.0.1:8080/?api=http://localhost:8000
```

## Running the tests

Unit tests (pure modules, Node's built-in runner):

```bash
cd web
npm test          # === node --test
```

End-to-end browser smoke test (drives the real page against the dev server):

```bash
# from web/, with the dev server running on :8099 and Playwright available
python3 server.py --port 8099 &
node e2e/browser-smoke.mjs         # load → stage → apply → verify audit → rollback
```

The smoke test asserts that the page boots with no console errors, the
visualization renders the sample joints, staging enables apply, applying advances
the version and updates the tree, the audit chain verifies, and rollback removes
the change.
