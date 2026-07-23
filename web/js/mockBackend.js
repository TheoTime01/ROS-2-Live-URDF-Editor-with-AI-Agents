// In-memory mock of the `web_api_node` pipeline so the front-end is fully
// usable offline (demos, tests, and graceful degradation when no ROS backend is
// running). It mirrors the documented staged-edit flow:
//   read -> stage -> validate -> apply/reject -> rollback
// keeping an immutable version store and a hash-chained audit trail that mirror
// the Python `version_store` and `observability.audit` semantics.

import { validateModel, serializeUrdf, modelSummary } from "./urdf.js";
import { applyOperations, diffModels } from "./editops.js";

// A synchronous, stable hash for chaining audit entries. This mock only needs a
// deterministic chain to demonstrate tamper-evidence in the UI; the
// authoritative, cryptographic (SHA-256) audit trail lives in the Python
// `observability.audit` module. Keeping this synchronous avoids any async
// ordering hazards in the pipeline.
function hashHex(str) {
  // 64-bit-ish FNV-1a spread across two 32-bit lanes for a longer, stable hex.
  let h1 = 0x811c9dc5;
  let h2 = 0xc9dc5118;
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ ((c << 3) | (c >> 5)), 0x01000193) >>> 0;
  }
  const hex = (n) => (n >>> 0).toString(16).padStart(8, "0");
  return (hex(h1) + hex(h2)).padStart(64, "0");
}

const GENESIS = "0".repeat(64);

export class MockBackend {
  constructor(initialModel, { clock = () => Date.now() / 1000 } = {}) {
    this._clock = clock;
    this._versions = []; // [{id, model, ts}]
    this._audit = []; // [{seq, ts, actor, action, summary, from_version, to_version, diff, prev_hash, entry_hash}]
    this._staged = null; // {model, validation}
    this._listeners = new Set();
    this._seq = 0;
    if (initialModel) this._commit(initialModel, "human:init", "load", "initial model load", ["+ initial model"]);
  }

  // -- events -----------------------------------------------------------
  subscribe(fn) {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }
  _emit(event) {
    for (const fn of this._listeners) {
      try {
        fn(event);
      } catch (_e) {
        /* a broken listener must not break the pipeline */
      }
    }
  }

  // -- read -------------------------------------------------------------
  get currentVersion() {
    return this._versions[this._versions.length - 1] || null;
  }
  read() {
    const v = this.currentVersion;
    return v
      ? { version: v.id, urdf: serializeUrdf(v.model), model: v.model, summary: modelSummary(v.model) }
      : { version: null, urdf: "", model: null, summary: null };
  }

  // -- stage + validate -------------------------------------------------
  // Stage a batch of EditOperations against the current model, producing a
  // staged candidate and its ValidationResult without touching the live model.
  stage(operations) {
    const base = this.currentVersion ? this.currentVersion.model : { name: "robot", links: [], joints: [] };
    let candidate;
    try {
      candidate = applyOperations(base, operations);
    } catch (err) {
      const validation = {
        valid: false,
        errors: [{ code: "APPLY_FAILED", severity: "error", message: err.message }],
        warnings: [],
        suggested_repairs: [],
      };
      this._staged = { model: null, validation, operations };
      this._emit({ type: "staged", validation });
      return { staged: false, validation };
    }
    const validation = validateModel(candidate);
    this._staged = { model: candidate, validation, operations };
    this._emit({ type: "staged", validation, summary: modelSummary(candidate) });
    return { staged: true, validation, summary: modelSummary(candidate) };
  }

  // Stage a full replacement model (used when the user edits raw URDF text and
  // stages the whole document). Unlike stage(), the candidate is the given
  // model outright rather than the current model plus operations.
  stageModel(model) {
    const validation = validateModel(model);
    this._staged = { model: JSON.parse(JSON.stringify(model)), validation, operations: null };
    this._emit({ type: "staged", validation, summary: modelSummary(model) });
    return { staged: true, validation, summary: modelSummary(model) };
  }

  // Validate the current staged candidate (or an ad-hoc model) again.
  validate() {
    if (!this._staged || !this._staged.model)
      return { valid: false, errors: [{ code: "NO_STAGE", severity: "error", message: "nothing staged" }], warnings: [], suggested_repairs: [] };
    return this._staged.validation;
  }

  // -- apply ------------------------------------------------------------
  // Apply the staged candidate iff it passes deterministic validation.
  async apply(actor = "human:web") {
    if (!this._staged || !this._staged.model) {
      return { applied: false, reason: "nothing staged" };
    }
    if (!this._staged.validation.valid) {
      this._emit({ type: "rejected", validation: this._staged.validation });
      return { applied: false, reason: "validation failed", validation: this._staged.validation };
    }
    const from = this.currentVersion;
    const diff = from ? diffModels(from.model, this._staged.model) : ["+ initial model"];
    const version = this._commit(this._staged.model, actor, "apply",
      diff.length ? diff.join("; ") : "no-op", diff);
    this._staged = null;
    this._emit({ type: "applied", version: version.id });
    return { applied: true, version: version.id, diff };
  }

  // -- rollback ---------------------------------------------------------
  async rollback(targetVersionId = null, actor = "human:web") {
    if (this._versions.length < 2) return { rolledBack: false, reason: "no earlier version" };
    let target;
    if (targetVersionId) {
      target = this._versions.find((v) => v.id === targetVersionId);
      if (!target) return { rolledBack: false, reason: `unknown version ${targetVersionId}` };
    } else {
      target = this._versions[this._versions.length - 2];
    }
    const from = this.currentVersion;
    const diff = diffModels(from.model, target.model);
    const version = this._commit(target.model, actor, "rollback",
      `rollback to ${target.id}`, diff, target.id);
    this._staged = null;
    this._emit({ type: "rolledBack", version: version.id, to: target.id });
    return { rolledBack: true, version: version.id, restored: target.id };
  }

  // -- versions + audit -------------------------------------------------
  versions() {
    return this._versions.map((v) => ({ id: v.id, ts: v.ts, summary: modelSummary(v.model) }));
  }
  audit() {
    return this._audit.slice();
  }

  // Returns { intact, problems }. Async signature kept for interface symmetry
  // with the HTTP backend; the work itself is synchronous.
  async verifyAudit() {
    let prev = GENESIS;
    const problems = [];
    for (let i = 0; i < this._audit.length; i++) {
      const e = this._audit[i];
      if (e.seq !== i) problems.push(`entry ${i}: bad seq`);
      if (e.prev_hash !== prev) problems.push(`entry ${i}: broken chain`);
      if (this._hashEntry(e) !== e.entry_hash) problems.push(`entry ${i}: tampered`);
      prev = e.entry_hash;
    }
    return { intact: problems.length === 0, problems };
  }

  _hashEntry(e) {
    const payload = JSON.stringify({
      seq: e.seq, ts: e.ts, actor: e.actor, action: e.action,
      summary: e.summary, from_version: e.from_version, to_version: e.to_version,
      diff: e.diff, prev_hash: e.prev_hash,
    });
    return hashHex(payload);
  }

  _commit(model, actor, action, summary, diff = null, restored = null) {
    const from = this.currentVersion;
    const id = `v${this._versions.length + 1}`;
    const ts = this._clock();
    const version = { id, model: JSON.parse(JSON.stringify(model)), ts };
    this._versions.push(version);

    const seq = this._seq++;
    const prev_hash = this._audit.length ? this._audit[this._audit.length - 1].entry_hash : GENESIS;
    const entry = {
      seq, ts, actor, action, summary,
      from_version: from ? from.id : null,
      to_version: id,
      diff,
      prev_hash,
    };
    entry.entry_hash = this._hashEntry(entry);
    this._audit.push(entry);
    this._emit({ type: "committed", version: id, action });
    return version;
  }
}
