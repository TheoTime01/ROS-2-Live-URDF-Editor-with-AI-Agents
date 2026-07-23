// URDF model: parsing, serialization, and deterministic validation.
//
// This is a browser- and Node-friendly mirror of the semantics enforced by the
// Python deterministic core (`urdf_live_editor`). It lets the web front-end
// validate edits instantly for a responsive UI *and* run offline in the mock
// backend. The authoritative validation still lives server-side; this module
// deliberately implements the same rules so the two agree.
//
// A "model" is a plain object:
//   { name, links: [{name}], joints: [{name,type,parent,child,axis,limit,origin}] }
// where `axis` is [x,y,z] | null, `limit` is {lower,upper,effort,velocity} | null.

const MOVABLE = new Set(["revolute", "continuous", "prismatic"]);
const KNOWN_TYPES = new Set([
  "revolute",
  "continuous",
  "prismatic",
  "fixed",
  "floating",
  "planar",
]);

// --------------------------------------------------------------------------
// A tiny, dependency-free XML reader for the URDF subset we care about.
// It is intentionally small: it understands elements, attributes, self-closing
// tags, comments, and the XML declaration. It is not a general XML parser.
// --------------------------------------------------------------------------
function tokenizeXml(xml) {
  const tokens = [];
  let i = 0;
  const n = xml.length;
  while (i < n) {
    if (xml[i] === "<") {
      const close = xml.indexOf(">", i);
      if (close === -1) throw new Error("unterminated tag");
      let raw = xml.slice(i + 1, close);
      i = close + 1;
      if (raw.startsWith("!--")) {
        // comment: skip to matching --> (raw may not contain it)
        if (!raw.endsWith("--")) {
          const end = xml.indexOf("-->", close);
          if (end === -1) throw new Error("unterminated comment");
          i = end + 3;
        }
        continue;
      }
      if (raw.startsWith("?") || raw.startsWith("!")) continue; // declaration / doctype
      const selfClosing = raw.endsWith("/");
      if (selfClosing) raw = raw.slice(0, -1).trim();
      const isClose = raw.startsWith("/");
      if (isClose) {
        tokens.push({ type: "close", name: raw.slice(1).trim() });
      } else {
        const { name, attrs } = parseTag(raw);
        tokens.push({ type: "open", name, attrs });
        if (selfClosing) tokens.push({ type: "close", name });
      }
    } else {
      // text node — ignored for URDF structure
      const next = xml.indexOf("<", i);
      i = next === -1 ? n : next;
    }
  }
  return tokens;
}

function parseTag(raw) {
  const spaceIdx = raw.search(/\s/);
  if (spaceIdx === -1) return { name: raw.trim(), attrs: {} };
  const name = raw.slice(0, spaceIdx).trim();
  const attrs = {};
  const attrRe = /([\w:-]+)\s*=\s*"([^"]*)"|([\w:-]+)\s*=\s*'([^']*)'/g;
  let m;
  const rest = raw.slice(spaceIdx);
  while ((m = attrRe.exec(rest)) !== null) {
    const key = m[1] ?? m[3];
    const val = m[2] ?? m[4];
    attrs[key] = val;
  }
  return { name, attrs };
}

function numbers(str) {
  return str
    .trim()
    .split(/\s+/)
    .filter((s) => s.length > 0)
    .map(Number);
}

// Parse a URDF XML string into a model object. Throws on malformed XML or a
// non-<robot> document.
export function parseUrdf(xml) {
  let tokens;
  try {
    tokens = tokenizeXml(xml);
  } catch (err) {
    throw new Error(`URDF is not well-formed XML: ${err.message}`);
  }
  const stack = [];
  let robot = null;
  let currentJoint = null;

  for (const tok of tokens) {
    if (tok.type === "open") {
      const parentTag = stack[stack.length - 1];
      stack.push(tok.name);
      if (tok.name === "robot") {
        robot = { name: tok.attrs.name || "robot", links: [], joints: [] };
      } else if (!robot) {
        throw new Error(`expected <robot> root element, got <${tok.name}>`);
      } else if (tok.name === "link" && parentTag === "robot") {
        robot.links.push({ name: tok.attrs.name || "" });
      } else if (tok.name === "joint" && parentTag === "robot") {
        currentJoint = {
          name: tok.attrs.name || "",
          type: (tok.attrs.type || "").toLowerCase(),
          parent: null,
          child: null,
          axis: null,
          limit: null,
          origin: null,
        };
        robot.joints.push(currentJoint);
      } else if (currentJoint && tok.name === "parent") {
        currentJoint.parent = tok.attrs.link || null;
      } else if (currentJoint && tok.name === "child") {
        currentJoint.child = tok.attrs.link || null;
      } else if (currentJoint && tok.name === "axis") {
        currentJoint.axis = tok.attrs.xyz ? numbers(tok.attrs.xyz) : null;
      } else if (currentJoint && tok.name === "limit") {
        const lim = {};
        for (const k of ["lower", "upper", "effort", "velocity"]) {
          if (tok.attrs[k] !== undefined) lim[k] = Number(tok.attrs[k]);
        }
        currentJoint.limit = lim;
      } else if (currentJoint && tok.name === "origin") {
        currentJoint.origin = {
          xyz: tok.attrs.xyz ? numbers(tok.attrs.xyz) : [0, 0, 0],
          rpy: tok.attrs.rpy ? numbers(tok.attrs.rpy) : [0, 0, 0],
        };
      }
    } else if (tok.type === "close") {
      stack.pop();
      if (tok.name === "joint") currentJoint = null;
    }
  }
  if (!robot) throw new Error("expected <robot> root element");
  return robot;
}

function attr(name, value) {
  return `${name}="${value}"`;
}

// Serialize a model object back into a URDF XML string.
export function serializeUrdf(model) {
  const lines = ['<?xml version="1.0"?>', `<robot ${attr("name", model.name || "robot")}>`];
  for (const link of model.links) {
    lines.push(`  <link ${attr("name", link.name)}/>`);
  }
  for (const j of model.joints) {
    lines.push(`  <joint ${attr("name", j.name)} ${attr("type", j.type)}>`);
    if (j.parent) lines.push(`    <parent ${attr("link", j.parent)}/>`);
    if (j.child) lines.push(`    <child ${attr("link", j.child)}/>`);
    if (j.axis) lines.push(`    <axis ${attr("xyz", j.axis.join(" "))}/>`);
    if (j.limit) {
      const parts = ["lower", "upper", "effort", "velocity"]
        .filter((k) => j.limit[k] !== undefined)
        .map((k) => attr(k, j.limit[k]));
      lines.push(`    <limit ${parts.join(" ")}/>`);
    }
    if (j.origin) {
      lines.push(
        `    <origin ${attr("xyz", j.origin.xyz.join(" "))} ${attr("rpy", j.origin.rpy.join(" "))}/>`
      );
    }
    lines.push("  </joint>");
  }
  lines.push("</robot>");
  return lines.join("\n") + "\n";
}

function err(code, message, extra = {}) {
  return { code, severity: "error", message, ...extra };
}
function warn(code, message, extra = {}) {
  return { code, severity: "warning", message, ...extra };
}

// Validate a model, returning a ValidationResult matching the README schema:
//   { valid, errors[], warnings[], suggested_repairs[] }
export function validateModel(model) {
  const errors = [];
  const warnings = [];
  const suggested = [];

  // --- schema: unique names, references resolve --------------------------
  const linkNames = new Set();
  for (const link of model.links) {
    if (!link.name) errors.push(err("EMPTY_LINK_NAME", "a <link> has no name"));
    else if (linkNames.has(link.name))
      errors.push(err("DUPLICATE_LINK", `duplicate link name '${link.name}'`, { link: link.name }));
    else linkNames.add(link.name);
  }

  const jointNames = new Set();
  for (const j of model.joints) {
    if (!j.name) {
      errors.push(err("EMPTY_JOINT_NAME", "a <joint> has no name"));
      continue;
    }
    if (jointNames.has(j.name))
      errors.push(err("DUPLICATE_JOINT", `duplicate joint name '${j.name}'`, { joint: j.name }));
    else jointNames.add(j.name);

    if (!KNOWN_TYPES.has(j.type))
      errors.push(err("UNKNOWN_JOINT_TYPE", `joint '${j.name}' has unknown type '${j.type}'`, { joint: j.name }));
    if (j.parent && !linkNames.has(j.parent))
      errors.push(err("BAD_PARENT", `joint '${j.name}' references missing parent '${j.parent}'`, { joint: j.name }));
    if (j.child && !linkNames.has(j.child))
      errors.push(err("BAD_CHILD", `joint '${j.name}' references missing child '${j.child}'`, { joint: j.name }));
    if (!j.parent) errors.push(err("MISSING_PARENT", `joint '${j.name}' has no parent link`, { joint: j.name }));
    if (!j.child) errors.push(err("MISSING_CHILD", `joint '${j.name}' has no child link`, { joint: j.name }));

    // --- per-joint rules -------------------------------------------------
    if (MOVABLE.has(j.type) && (!j.axis || j.axis.length !== 3)) {
      errors.push(err("MISSING_AXIS", `${j.type} joint '${j.name}' requires an <axis>`, { joint: j.name }));
      suggested.push({
        operation: "set_joint_axis",
        target: { name: j.name, axis: [0, 0, 1] },
        reason: `Add a default Z axis so ${j.type} joint '${j.name}' has a rotation/translation axis.`,
      });
    }
    if (j.type === "revolute" || j.type === "prismatic") {
      const hasFinite =
        j.limit && Number.isFinite(j.limit.lower) && Number.isFinite(j.limit.upper);
      if (!hasFinite) {
        errors.push(err("MISSING_LIMIT", `${j.type} joint '${j.name}' requires finite lower/upper limits`, { joint: j.name }));
        suggested.push({
          operation: "set_joint_limit",
          target: { name: j.name, limit: { lower: -1.5708, upper: 1.5708 } },
          reason: `Add symmetric limits so the ${j.type} joint '${j.name}' is bounded.`,
        });
      } else if (j.limit.lower > j.limit.upper) {
        errors.push(err("INVERTED_LIMIT", `joint '${j.name}' has lower > upper`, { joint: j.name }));
      }
      if (j.limit) {
        for (const k of ["effort", "velocity"]) {
          if (j.limit[k] !== undefined && j.limit[k] < 0)
            errors.push(err("NEGATIVE_LIMIT", `joint '${j.name}' has negative ${k}`, { joint: j.name }));
        }
      }
    }
    if (j.type === "continuous" && j.limit &&
        Number.isFinite(j.limit.lower) && Number.isFinite(j.limit.upper)) {
      warnings.push(warn("CONTINUOUS_HAS_LIMIT",
        `continuous joint '${j.name}' carries finite limits; it should wrap, not clamp`, { joint: j.name }));
      suggested.push({
        operation: "update_joint",
        target: { name: j.name, limit: null },
        reason: `Remove finite limits from continuous joint '${j.name}' so it wraps.`,
      });
    }
    if (j.type === "fixed" && j.limit &&
        (Number.isFinite(j.limit.lower) || Number.isFinite(j.limit.upper))) {
      errors.push(err("FIXED_HAS_LIMIT", `fixed joint '${j.name}' must not carry a motion limit`, { joint: j.name }));
    }
  }

  // --- topology: single connected tree, one root -------------------------
  if (model.links.length > 0) {
    const childLinks = new Set(model.joints.map((j) => j.child).filter(Boolean));
    const roots = [...linkNames].filter((l) => !childLinks.has(l));
    if (roots.length === 0)
      errors.push(err("NO_ROOT", "no root link found (every link is a child — cycle?)"));
    else if (roots.length > 1)
      errors.push(err("MULTIPLE_ROOTS", `expected exactly one root link, found ${roots.length}: ${roots.join(", ")}`));

    // orphan detection + cycle detection via BFS from the (single) root
    if (roots.length === 1) {
      const adj = new Map();
      for (const l of linkNames) adj.set(l, []);
      for (const j of model.joints) {
        if (j.parent && j.child && adj.has(j.parent)) adj.get(j.parent).push(j.child);
      }
      const seen = new Set();
      const queue = [roots[0]];
      while (queue.length) {
        const cur = queue.shift();
        if (seen.has(cur)) {
          errors.push(err("CYCLE", `cycle detected involving link '${cur}'`));
          break;
        }
        seen.add(cur);
        for (const nxt of adj.get(cur) || []) queue.push(nxt);
      }
      const orphans = [...linkNames].filter((l) => !seen.has(l));
      if (orphans.length && !errors.some((e) => e.code === "CYCLE"))
        warnings.push(warn("ORPHAN_LINKS", `links not connected to root: ${orphans.join(", ")}`));
    }
  }

  return { valid: errors.length === 0, errors, warnings, suggested_repairs: suggested };
}

export function modelSummary(model) {
  return {
    name: model.name,
    linkCount: model.links.length,
    jointCount: model.joints.length,
    movableJoints: model.joints.filter((j) => MOVABLE.has(j.type)).map((j) => j.name),
  };
}

export { MOVABLE, KNOWN_TYPES };
