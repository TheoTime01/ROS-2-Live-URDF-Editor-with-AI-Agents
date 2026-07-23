import { test } from "node:test";
import assert from "node:assert/strict";
import { MockBackend } from "../js/mockBackend.js";
import { parseUrdf } from "../js/urdf.js";

const URDF = `<robot name="arm">
  <link name="base_link"/><link name="l1"/>
  <joint name="j1" type="revolute">
    <parent link="base_link"/><child link="l1"/>
    <axis xyz="0 0 1"/><limit lower="-1" upper="1"/>
  </joint>
</robot>`;

function backend() {
  let t = 1000;
  return new MockBackend(parseUrdf(URDF), { clock: () => (t += 1) });
}

test("read returns the initial model", () => {
  const b = backend();
  const r = b.read();
  assert.equal(r.version, "v1");
  assert.equal(r.summary.jointCount, 1);
});

test("stage + apply advances the version and records audit", async () => {
  const b = backend();
  const staged = b.stage([
    { operation: "add_joint", target: { name: "j2", type: "revolute", parent: "l1",
      child: "l2", axis: [0, 1, 0], limit: { lower: -1, upper: 1 } } },
  ]);
  assert.equal(staged.staged, true);
  assert.equal(staged.validation.valid, true);

  const applied = await b.apply("human:test");
  assert.equal(applied.applied, true);
  assert.equal(applied.version, "v2");
  assert.equal(b.read().summary.jointCount, 2);
  assert.equal(b.audit().length, 2); // load + apply
});

test("apply is rejected when validation fails", async () => {
  const b = backend();
  // revolute joint missing its limit -> invalid
  b.stage([
    { operation: "add_joint", target: { name: "bad", type: "revolute", parent: "l1", child: "l2" } },
  ]);
  const applied = await b.apply();
  assert.equal(applied.applied, false);
  assert.equal(applied.reason, "validation failed");
  assert.equal(b.read().version, "v1"); // unchanged
});

test("stage reports apply failures (e.g. duplicate) as validation errors", () => {
  const b = backend();
  const res = b.stage([{ operation: "add_joint", target: { name: "j1" } }]);
  assert.equal(res.staged, false);
  assert.ok(res.validation.errors.some((e) => e.code === "APPLY_FAILED"));
});

test("rollback restores the previous version", async () => {
  const b = backend();
  b.stage([
    { operation: "add_joint", target: { name: "j2", type: "revolute", parent: "l1",
      child: "l2", axis: [0, 1, 0], limit: { lower: -1, upper: 1 } } },
  ]);
  await b.apply();
  assert.equal(b.read().summary.jointCount, 2);
  const rb = await b.rollback();
  assert.equal(rb.rolledBack, true);
  assert.equal(b.read().summary.jointCount, 1); // back to just j1
});

test("audit trail is hash-chained and intact", async () => {
  const b = backend();
  b.stage([{ operation: "add_link", target: { name: "extra" } }]);
  // add_link alone leaves a dangling link -> warning only, still valid tree? It
  // becomes a second root, which is an error; apply should be rejected. Use a
  // valid edit instead:
  b.stage([
    { operation: "add_joint", target: { name: "j2", type: "continuous", parent: "l1",
      child: "l2", axis: [1, 0, 0] } },
  ]);
  await b.apply();
  const check = await b.verifyAudit();
  assert.equal(check.intact, true, JSON.stringify(check.problems));
});

test("tampering with the audit trail is detected", async () => {
  const b = backend();
  b.stage([
    { operation: "add_joint", target: { name: "j2", type: "continuous", parent: "l1",
      child: "l2", axis: [1, 0, 0] } },
  ]);
  await b.apply();
  b.audit(); // snapshot
  b._audit[0].summary = "hacked"; // mutate internal state
  const check = await b.verifyAudit();
  assert.equal(check.intact, false);
});

test("stageModel stages a full replacement candidate", async () => {
  const b = backend();
  const replacement = {
    name: "arm",
    links: [{ name: "base_link" }, { name: "l1" }, { name: "l2" }],
    joints: [
      { name: "j1", type: "revolute", parent: "base_link", child: "l1",
        axis: [0, 0, 1], limit: { lower: -1, upper: 1 }, origin: null },
      { name: "j2", type: "continuous", parent: "l1", child: "l2",
        axis: [1, 0, 0], limit: null, origin: null },
    ],
  };
  const res = b.stageModel(replacement);
  assert.equal(res.staged, true);
  assert.equal(res.validation.valid, true);
  const applied = await b.apply();
  assert.equal(applied.applied, true);
  assert.equal(b.read().summary.jointCount, 2);
});

test("events are emitted to subscribers", async () => {
  const b = backend();
  const events = [];
  const unsub = b.subscribe((e) => events.push(e.type));
  b.stage([
    { operation: "add_joint", target: { name: "j2", type: "continuous", parent: "l1",
      child: "l2", axis: [1, 0, 0] } },
  ]);
  await b.apply();
  unsub();
  assert.ok(events.includes("staged"));
  assert.ok(events.includes("applied"));
});
