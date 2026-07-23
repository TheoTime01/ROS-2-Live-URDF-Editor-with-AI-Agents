# Web front-end

A dependency-free, no-build web UI for the ROS 2 Live URDF Editor (Milestone 5).
It provides live URDF editing, an instant deterministic-validation view, a
kinematic-tree visualization, version history, a diagnostics dashboard, and an
**audit-trail viewer** with hash-chain integrity checking.

## Running

```bash
cd web
python3 server.py            # serves http://127.0.0.1:8080
# or: npm run serve
```

Open <http://127.0.0.1:8080>. With no ROS backend running, the app uses an
in-browser **mock backend** that faithfully reproduces the staged-edit pipeline
(stage → validate → apply/reject → rollback) with an immutable version store and
a hash-chained audit trail, so the UI is fully usable offline for demos and
tests.

To point the UI at a real `web_api_node` (Milestone 3) instead:

```
http://127.0.0.1:8080/?api=http://localhost:8000
```

The client probes that URL and falls back to the mock automatically if it is
unreachable.

## Architecture

All non-trivial logic lives in small, pure ES modules that are unit-tested with
Node's built-in test runner; `app.js` is only DOM glue.

| Module | Responsibility |
|---|---|
| `js/urdf.js` | URDF parse/serialize + deterministic validation (mirrors the Python core's rules) |
| `js/editops.js` | Apply `EditOperation`s to a model; structured diffs |
| `js/mockBackend.js` | In-memory staged-edit pipeline, version store, hash-chained audit |
| `js/api.js` | Uniform client over the mock or a real REST/WebSocket backend |
| `js/viz.js` | Kinematic-tree SVG renderer |
| `js/format.js` | Pure formatting/derivation helpers |
| `js/app.js` | DOM controller (glue only) |

The documented REST/WebSocket contract the HTTP client targets is listed in
`ROUTES` in `js/api.js`.

## Testing

```bash
cd web
npm test          # node --test — pure-module unit tests
```

An end-to-end browser smoke test (Playwright) drives the real page against the
dev server: load → visualize → stage → apply → verify audit integrity →
rollback. See `docs/tutorials/web-ui.md` for how to run it.
