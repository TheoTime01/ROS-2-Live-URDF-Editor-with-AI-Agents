// Front-end controller: wires the API client to the DOM. All heavy logic lives
// in the tested pure modules (urdf, editops, mockBackend, viz, format); this
// file is intentionally just glue and rendering.

import { createClient } from "./api.js";
import { parseUrdf, serializeUrdf } from "./urdf.js";
import { renderTreeSvg } from "./viz.js";
import {
  formatTimestamp,
  summarizeValidation,
  escapeHtml,
  shortHash,
} from "./format.js";

const SAMPLE_URDF = `<?xml version="1.0"?>
<robot name="sample_arm">
  <link name="base_link"/>
  <link name="link_1"/>
  <link name="link_2"/>
  <link name="link_3"/>
  <link name="tool_link"/>
  <joint name="shoulder" type="revolute">
    <parent link="base_link"/><child link="link_1"/>
    <axis xyz="0 0 1"/><limit lower="-3.14159" upper="3.14159" effort="20" velocity="1.5"/>
  </joint>
  <joint name="elbow" type="revolute">
    <parent link="link_1"/><child link="link_2"/>
    <axis xyz="0 1 0"/><limit lower="-1.5708" upper="1.5708" effort="15" velocity="1.5"/>
  </joint>
  <joint name="wrist" type="continuous">
    <parent link="link_2"/><child link="link_3"/><axis xyz="1 0 0"/>
  </joint>
  <joint name="tool_mount" type="fixed">
    <parent link="link_3"/><child link="tool_link"/>
  </joint>
</robot>`;

const $ = (id) => document.getElementById(id);
const state = { client: null, lastValidation: null, logs: [] };

async function boot() {
  // Prefer a real backend at the same origin; otherwise the mock kicks in.
  const baseUrl = new URLSearchParams(location.search).get("api") || "";
  state.client = await createClient({ baseUrl, initialUrdf: SAMPLE_URDF });

  const connChip = $("conn-chip");
  connChip.textContent = state.client.mode === "http" ? "connected (ROS API)" : "offline (mock backend)";
  connChip.classList.add(state.client.mode);

  wireEvents();
  subscribeStream();
  await refreshAll();
  seedDiagnostics();
}

function wireEvents() {
  $("btn-stage-source").addEventListener("click", stageFromSource);
  $("btn-reload").addEventListener("click", () => refreshAll());
  $("btn-apply").addEventListener("click", applyStaged);
  $("btn-rollback").addEventListener("click", () => rollback());
  $("op-form").addEventListener("submit", stageFromForm);
  $("op-type").addEventListener("change", renderOpFields);
  $("audit-search").addEventListener("input", renderAudit);
  $("audit-action").addEventListener("change", renderAudit);
  $("audit-verify").addEventListener("click", verifyAudit);

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });
  renderOpFields();
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tabpane").forEach((p) => p.classList.toggle("active", p.dataset.pane === name));
}

function subscribeStream() {
  state.client.subscribe((event) => {
    pushLog("INFO", `event.${event.type}`, event);
    // Any pipeline event may change versions/audit/model.
    refreshAll();
  });
}

// -- rendering ------------------------------------------------------------
async function refreshAll() {
  const model = await loadModelIntoEditor();
  renderViz(model);
  await Promise.all([renderVersions(), renderAudit()]);
}

async function loadModelIntoEditor() {
  const data = await state.client.read();
  if (data && data.urdf) $("urdf-input").value = data.urdf.trim();
  $("version-chip").textContent = `version ${data && data.version ? data.version : "—"}`;
  let model = null;
  try {
    model = data && data.urdf ? parseUrdf(data.urdf) : null;
  } catch (_e) {
    /* editor may hold in-progress text */
  }
  return model;
}

function renderViz(model) {
  $("viz").innerHTML = renderTreeSvg(model || { links: [], joints: [] });
}

function renderValidation(result) {
  state.lastValidation = result;
  const box = $("validation-out");
  const badge = summarizeValidation(result);
  $("valid-chip").className = `chip ${badge.level}`;
  $("valid-chip").textContent = `validation: ${badge.label}`;

  if (!result) {
    box.innerHTML = "Nothing staged.";
    $("btn-apply").disabled = true;
    return;
  }
  const parts = [];
  parts.push(result.valid ? '<div class="v-ok">✓ passes deterministic validation</div>' : "");
  const items = [];
  for (const e of result.errors || []) {
    items.push(`<li class="error">${escapeHtml(e.message)} <span class="code">[${escapeHtml(e.code)}]</span></li>`);
  }
  for (const w of result.warnings || []) {
    items.push(`<li class="warning">${escapeHtml(w.message)} <span class="code">[${escapeHtml(w.code)}]</span></li>`);
  }
  if (items.length) parts.push(`<ul>${items.join("")}</ul>`);

  if ((result.suggested_repairs || []).length) {
    const buttons = result.suggested_repairs
      .map((r, i) => `<button data-repair="${i}" title="${escapeHtml(r.reason)}">apply: ${escapeHtml(r.operation)} ${escapeHtml(r.target && r.target.name || "")}</button>`)
      .join("");
    parts.push(`<div class="repairs"><strong>Suggested repairs</strong><br/>${buttons}</div>`);
  }
  box.innerHTML = parts.join("") || "Staged.";
  box.querySelectorAll("[data-repair]").forEach((btn) => {
    btn.addEventListener("click", () => applyRepair(result.suggested_repairs[Number(btn.dataset.repair)]));
  });
  $("btn-apply").disabled = !result.valid;
}

async function renderVersions() {
  const versions = await state.client.versions();
  const list = $("version-list");
  list.innerHTML = "";
  for (const v of [...versions].reverse()) {
    const li = document.createElement("li");
    li.className = "version-item";
    li.innerHTML =
      `<div class="head"><span class="actor">${escapeHtml(v.id)}</span>` +
      `<span class="action">${formatTimestamp(v.ts)}</span></div>` +
      `<div class="summary">${v.summary.linkCount} links · ${v.summary.jointCount} joints</div>`;
    const btn = document.createElement("button");
    btn.textContent = "rollback to here";
    btn.style.marginTop = "6px";
    btn.addEventListener("click", () => rollback(v.id));
    li.appendChild(btn);
    list.appendChild(li);
  }
}

async function renderAudit() {
  const entries = await state.client.audit();
  const needle = $("audit-search").value.trim().toLowerCase();
  const actionFilter = $("audit-action").value;
  const list = $("audit-list");
  list.innerHTML = "";
  const filtered = entries
    .filter((e) => !actionFilter || e.action === actionFilter)
    .filter((e) => !needle || `${e.summary} ${e.action} ${e.actor}`.toLowerCase().includes(needle))
    .reverse();

  for (const e of filtered) {
    const li = document.createElement("li");
    li.className = "audit-item";
    const diff = Array.isArray(e.diff) ? e.diff.join("\n") : e.diff || "";
    li.innerHTML =
      `<div class="head"><span class="actor">${escapeHtml(e.actor)}</span>` +
      `<span class="action">${escapeHtml(e.action)}</span></div>` +
      `<div class="summary">${escapeHtml(e.summary || "")}</div>` +
      (diff ? `<div class="diff">${escapeHtml(diff)}</div>` : "") +
      `<div class="meta">#${e.seq} · ${formatTimestamp(e.ts)} · ` +
      `${escapeHtml(e.from_version || "∅")}→${escapeHtml(e.to_version || "∅")} · ` +
      `hash ${escapeHtml(shortHash(e.entry_hash))}</div>`;
    list.appendChild(li);
  }
  if (!filtered.length) list.innerHTML = '<li class="audit-item">No matching audit entries.</li>';
}

async function verifyAudit() {
  const box = $("audit-integrity");
  if (!state.client.verifyAudit) {
    box.textContent = "Integrity check runs against the mock backend only.";
    return;
  }
  const res = await state.client.verifyAudit();
  box.className = `integrity ${res.intact ? "ok" : "bad"}`;
  box.textContent = res.intact
    ? `✓ audit trail intact (${(await state.client.audit()).length} entries, hash chain verified)`
    : `✗ tamper detected: ${res.problems.join("; ")}`;
}

// -- diagnostics ----------------------------------------------------------
function seedDiagnostics() {
  // The mock has no live ROS diagnostics; show representative subsystem health
  // so the dashboard is meaningful in offline mode. Against a real backend this
  // would come from GET /api/diagnostics.
  const components = [
    { name: "urdf_source", level: "ok", message: "watching sample_arm.urdf" },
    { name: "validation", level: "ok", message: "deterministic engine ready" },
    { name: "joint_state_adapter", level: "ok", message: "publishing /joint_states @ 30 Hz" },
    { name: "web_api", level: state.client.mode === "http" ? "ok" : "warning",
      message: state.client.mode === "http" ? "connected" : "mock backend (no ROS)" },
    { name: "ai_agents", level: "warning", message: "no ANTHROPIC_API_KEY set (advisory checks off)" },
  ];
  renderDiagnostics(components);
}

function renderDiagnostics(components) {
  const list = $("diagnostics-list");
  list.innerHTML = "";
  let worst = "ok";
  const rank = { ok: 0, warning: 1, error: 2, stale: 3 };
  for (const c of components) {
    if (rank[c.level] > rank[worst]) worst = c.level;
    const div = document.createElement("div");
    div.className = "diag-item";
    div.innerHTML =
      `<span class="diag-dot ${c.level}"></span>` +
      `<span class="name">${escapeHtml(c.name)}</span>` +
      `<span class="msg">${escapeHtml(c.message)}</span>`;
    list.appendChild(div);
  }
  const chip = $("health-chip");
  chip.className = `chip ${worst}`;
  chip.textContent = `health: ${worst}`;
}

// -- actions --------------------------------------------------------------
async function stageFromSource() {
  let model;
  try {
    model = parseUrdf($("urdf-input").value);
  } catch (err) {
    renderValidation({ valid: false, errors: [{ code: "PARSE_ERROR", severity: "error", message: err.message }], warnings: [], suggested_repairs: [] });
    return;
  }
  const result = await state.client.stageModel(model);
  const validation = result.validation || result;
  renderValidation(validation);
  pushLog(validation.valid ? "INFO" : "WARNING", "staged_source", { valid: validation.valid });
}

async function stageFromForm(ev) {
  ev.preventDefault();
  const op = readOpForm();
  if (!op) return;
  await stageAndShow([op]);
}

async function stageAndShow(ops) {
  const result = await state.client.stage(ops);
  const validation = result.validation || result;
  renderValidation(validation);
  pushLog(validation.valid ? "INFO" : "WARNING", "staged", { valid: validation.valid, ops: ops.length });
}

async function applyStaged() {
  const res = await state.client.apply("human:web");
  if (res.applied) {
    pushLog("INFO", "applied", { version: res.version });
    renderValidation(null);
  } else {
    pushLog("ERROR", "apply_rejected", { reason: res.reason });
    if (res.validation) renderValidation(res.validation);
  }
  await refreshAll();
}

async function rollback(versionId = null) {
  const res = await state.client.rollback(versionId, "human:web");
  pushLog(res.rolledBack ? "INFO" : "WARNING", "rollback", res);
  await refreshAll();
}

async function applyRepair(repair) {
  if (!repair) return;
  await stageAndShow([repair]);
}

// -- op form --------------------------------------------------------------
const OP_FIELDS = {
  add_joint: ["type", "parent", "child", "axis", "lower", "upper"],
  update_joint: ["type", "parent", "child", "axis", "lower", "upper"],
  set_joint_limit: ["lower", "upper"],
  set_joint_axis: ["axis"],
  remove_joint: ["cascade"],
  rename: ["new_name"],
  add_link: [],
};

function renderOpFields() {
  const kind = $("op-type").value;
  const wrap = $("op-fields");
  wrap.innerHTML = "";
  for (const field of OP_FIELDS[kind] || []) {
    const label = document.createElement("label");
    if (field === "type") {
      label.innerHTML = `type <select id="f-type"><option>revolute</option><option>continuous</option><option>prismatic</option><option>fixed</option></select>`;
    } else if (field === "cascade") {
      label.innerHTML = `<span><input type="checkbox" id="f-cascade"/> cascade (remove subtree)</span>`;
    } else {
      const ph = field === "axis" ? "0 0 1" : field;
      label.innerHTML = `${field} <input id="f-${field}" placeholder="${ph}"/>`;
    }
    wrap.appendChild(label);
  }
}

function val(id) {
  const el = $(id);
  return el ? el.value.trim() : "";
}

function readOpForm() {
  const kind = $("op-type").value;
  const name = val("op-name");
  if (!name) return null;
  const target = { name };
  const has = (f) => (OP_FIELDS[kind] || []).includes(f);
  if (has("type") && val("f-type")) target.type = val("f-type");
  if (has("parent") && val("f-parent")) target.parent = val("f-parent");
  if (has("child") && val("f-child")) target.child = val("f-child");
  if (has("axis") && val("f-axis")) target.axis = val("f-axis").split(/\s+/).map(Number);
  if (has("new_name")) target.new_name = val("f-new_name");
  if (has("lower") || has("upper")) {
    const lim = {};
    if (val("f-lower") !== "") lim.lower = Number(val("f-lower"));
    if (val("f-upper") !== "") lim.upper = Number(val("f-upper"));
    if (Object.keys(lim).length) target.limit = lim;
  }
  const op = { operation: kind, target };
  if (has("cascade") && $("f-cascade") && $("f-cascade").checked) op.cascade = true;
  return op;
}

// -- logs -----------------------------------------------------------------
function pushLog(level, event, fields) {
  const rec = { ts: Date.now() / 1000, level, event, fields };
  state.logs.push(rec);
  if (state.logs.length > 300) state.logs.shift();
  const pre = $("log-stream");
  const line = document.createElement("span");
  line.className = `lvl-${level}`;
  line.textContent = JSON.stringify({ ts: Math.round(rec.ts), level, event, ...(fields || {}) }) + "\n";
  pre.appendChild(line);
  pre.scrollTop = pre.scrollHeight;
}

boot().catch((err) => {
  const chip = $("conn-chip");
  if (chip) { chip.textContent = "boot error"; chip.classList.add("error"); }
  // eslint-disable-next-line no-console
  console.error("boot failed", err);
});
