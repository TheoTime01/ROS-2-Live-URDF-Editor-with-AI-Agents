import { test } from "node:test";
import assert from "node:assert/strict";
import { parseUrdf, serializeUrdf, validateModel, modelSummary } from "../js/urdf.js";

const SAMPLE = `<?xml version="1.0"?>
<robot name="sample_arm">
  <link name="base_link"/>
  <link name="link_1"/>
  <link name="link_2"/>
  <joint name="shoulder" type="revolute">
    <parent link="base_link"/><child link="link_1"/>
    <axis xyz="0 0 1"/><limit lower="-3.14" upper="3.14"/>
  </joint>
  <joint name="wrist" type="continuous">
    <parent link="link_1"/><child link="link_2"/><axis xyz="1 0 0"/>
  </joint>
</robot>`;

test("parseUrdf extracts links and joints", () => {
  const m = parseUrdf(SAMPLE);
  assert.equal(m.name, "sample_arm");
  assert.equal(m.links.length, 3);
  assert.equal(m.joints.length, 2);
  const shoulder = m.joints.find((j) => j.name === "shoulder");
  assert.equal(shoulder.type, "revolute");
  assert.deepEqual(shoulder.axis, [0, 0, 1]);
  assert.equal(shoulder.limit.lower, -3.14);
});

test("parseUrdf rejects malformed XML", () => {
  assert.throws(() => parseUrdf("<robot><link"), /well-formed|unterminated/);
});

test("parseUrdf rejects non-robot root", () => {
  assert.throws(() => parseUrdf("<world/>"), /robot/);
});

test("serializeUrdf round-trips through parseUrdf", () => {
  const m = parseUrdf(SAMPLE);
  const xml = serializeUrdf(m);
  const m2 = parseUrdf(xml);
  assert.equal(m2.joints.length, m.joints.length);
  assert.equal(m2.links.length, m.links.length);
  assert.deepEqual(modelSummary(m2).movableJoints, ["shoulder", "wrist"]);
});

test("validateModel passes a good model", () => {
  const res = validateModel(parseUrdf(SAMPLE));
  assert.equal(res.valid, true);
  assert.deepEqual(res.errors, []);
});

test("validateModel flags revolute without limit", () => {
  const m = parseUrdf(SAMPLE);
  m.joints.find((j) => j.name === "shoulder").limit = null;
  const res = validateModel(m);
  assert.equal(res.valid, false);
  assert.ok(res.errors.some((e) => e.code === "MISSING_LIMIT"));
  assert.ok(res.suggested_repairs.some((r) => r.operation === "set_joint_limit"));
});

test("validateModel flags revolute without axis", () => {
  const m = parseUrdf(SAMPLE);
  m.joints.find((j) => j.name === "shoulder").axis = null;
  const res = validateModel(m);
  assert.ok(res.errors.some((e) => e.code === "MISSING_AXIS"));
});

test("validateModel warns continuous with finite limit", () => {
  const m = parseUrdf(SAMPLE);
  m.joints.find((j) => j.name === "wrist").limit = { lower: -1, upper: 1 };
  const res = validateModel(m);
  assert.ok(res.warnings.some((w) => w.code === "CONTINUOUS_HAS_LIMIT"));
});

test("validateModel flags missing parent link reference", () => {
  const m = parseUrdf(SAMPLE);
  m.joints.find((j) => j.name === "shoulder").parent = "ghost";
  const res = validateModel(m);
  assert.ok(res.errors.some((e) => e.code === "BAD_PARENT"));
});

test("validateModel flags multiple roots", () => {
  const m = parseUrdf(SAMPLE);
  m.links.push({ name: "floating_link" });
  const res = validateModel(m);
  assert.ok(res.errors.some((e) => e.code === "MULTIPLE_ROOTS"));
});

test("validateModel flags inverted limits", () => {
  const m = parseUrdf(SAMPLE);
  m.joints.find((j) => j.name === "shoulder").limit = { lower: 2, upper: -2 };
  const res = validateModel(m);
  assert.ok(res.errors.some((e) => e.code === "INVERTED_LIMIT"));
});
