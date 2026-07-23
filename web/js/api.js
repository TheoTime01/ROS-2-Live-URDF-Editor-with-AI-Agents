// A single client interface the UI talks to, with two interchangeable backends:
//
//   * MockBackend  — in-memory pipeline (offline demos, tests, degraded mode)
//   * HttpBackend  — REST + WebSocket to the real `web_api_node` (Milestone 3)
//
// The UI never branches on which backend is active; `createClient()` picks the
// HTTP backend when a base URL is reachable and otherwise falls back to the
// mock so the app is always usable.

import { MockBackend } from "./mockBackend.js";
import { parseUrdf, serializeUrdf } from "./urdf.js";

// The documented REST contract of web_api_node. Kept in one place so the mock
// and HTTP backends stay aligned with the server.
export const ROUTES = {
  read: "GET /api/model",
  stage: "POST /api/stage",
  validate: "POST /api/validate",
  apply: "POST /api/apply",
  rollback: "POST /api/rollback",
  versions: "GET /api/versions",
  audit: "GET /api/audit",
  diagnostics: "GET /api/diagnostics",
  events: "WS /api/events",
};

class MockClient {
  constructor(backend) {
    this.backend = backend;
    this.mode = "mock";
  }
  subscribe(fn) {
    return this.backend.subscribe(fn);
  }
  async read() {
    return this.backend.read();
  }
  async stage(ops) {
    return this.backend.stage(ops);
  }
  async stageModel(model) {
    return this.backend.stageModel(model);
  }
  async validate() {
    return this.backend.validate();
  }
  async apply(actor) {
    return this.backend.apply(actor);
  }
  async rollback(versionId, actor) {
    return this.backend.rollback(versionId, actor);
  }
  async versions() {
    return this.backend.versions();
  }
  async audit() {
    return this.backend.audit();
  }
  async verifyAudit() {
    return this.backend.verifyAudit();
  }
}

class HttpClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.mode = "http";
    this._ws = null;
    this._listeners = new Set();
  }
  async _json(method, path, body) {
    const res = await fetch(this.baseUrl + path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
    return res.json();
  }
  subscribe(fn) {
    this._listeners.add(fn);
    if (!this._ws && typeof WebSocket !== "undefined") {
      const wsUrl = this.baseUrl.replace(/^http/, "ws") + "/api/events";
      try {
        this._ws = new WebSocket(wsUrl);
        this._ws.onmessage = (m) => {
          let event;
          try {
            event = JSON.parse(m.data);
          } catch {
            return;
          }
          for (const l of this._listeners) l(event);
        };
      } catch {
        /* WS optional; REST still works */
      }
    }
    return () => this._listeners.delete(fn);
  }
  read() {
    return this._json("GET", "/api/model");
  }
  stage(ops) {
    return this._json("POST", "/api/stage", { operations: ops });
  }
  stageModel(model) {
    return this._json("POST", "/api/stage", { urdf: serializeUrdf(model) });
  }
  validate() {
    return this._json("POST", "/api/validate", {});
  }
  apply(actor) {
    return this._json("POST", "/api/apply", { actor });
  }
  rollback(versionId, actor) {
    return this._json("POST", "/api/rollback", { version: versionId, actor });
  }
  versions() {
    return this._json("GET", "/api/versions");
  }
  audit() {
    return this._json("GET", "/api/audit");
  }
  diagnostics() {
    return this._json("GET", "/api/diagnostics");
  }
}

// Probe whether an HTTP backend answers; if so use it, else fall back to mock.
export async function createClient({ baseUrl = "", initialUrdf = "" } = {}) {
  if (baseUrl && typeof fetch !== "undefined") {
    try {
      const res = await fetch(baseUrl.replace(/\/$/, "") + "/api/model", {
        method: "GET",
        signal: AbortSignal.timeout ? AbortSignal.timeout(1500) : undefined,
      });
      if (res.ok) return new HttpClient(baseUrl);
    } catch {
      /* fall through to mock */
    }
  }
  const model = initialUrdf ? parseUrdf(initialUrdf) : { name: "robot", links: [], joints: [] };
  return new MockClient(new MockBackend(model));
}

export { MockClient, HttpClient };
