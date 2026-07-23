import { test } from "node:test";
import assert from "node:assert/strict";
import { applyOperation, applyOperations, diffModels } from "../js/editops.js";
import { validateModel } from "../js/urdf.js";

function base() {
  return {
    name: "arm",
    links: [{ name: "base_link" }, { name: "link_1" }],
    joints: [
      {
        name: "shoulder",
        type: "revolute",
        parent: "base_link",
        child: "link_1",
        axis: [0, 0, 1],
        limit: { lower: -1, upper: 1 },
        origin: null,
      },
    ],
  };
}

test("add_joint appends and auto-creates child link", () => {
  const m = applyOperation(base(), {
    operation: "add_joint",
    target: { name: "elbow", type: "revolute", parent: "link_1", child: "link_2",
      axis: [0, 1, 0], limit: { lower: -1.5, upper: 1.5 } },
  });
  assert.equal(m.joints.length, 2);
  assert.ok(m.links.some((l) => l.name === "link_2"));
  assert.equal(validateModel(m).valid, true);
});

test("add_joint rejects duplicate name", () => {
  assert.throws(
    () => applyOperation(base(), { operation: "add_joint", target: { name: "shoulder" } }),
    /already exists/
  );
});

test("does not mutate the input model", () => {
  const m = base();
  applyOperation(m, { operation: "add_link", target: { name: "extra" } });
  assert.equal(m.links.length, 2);
});

test("set_joint_limit merges limit fields", () => {
  const m = applyOperation(base(), {
    operation: "set_joint_limit",
    target: { name: "shoulder", limit: { lower: -2, upper: 2 } },
  });
  assert.deepEqual(m.joints[0].limit, { lower: -2, upper: 2 });
});

test("set_joint_axis replaces axis", () => {
  const m = applyOperation(base(), {
    operation: "set_joint_axis",
    target: { name: "shoulder", axis: [1, 0, 0] },
  });
  assert.deepEqual(m.joints[0].axis, [1, 0, 0]);
});

test("rename updates joint and parent/child references", () => {
  const m = applyOperation(base(), {
    operation: "rename",
    target: { name: "link_1", new_name: "upper_arm" },
  });
  assert.ok(m.links.some((l) => l.name === "upper_arm"));
  assert.equal(m.joints[0].child, "upper_arm");
});

test("remove_joint with cascade removes subtree", () => {
  let m = applyOperations(base(), [
    { operation: "add_joint", target: { name: "elbow", type: "revolute", parent: "link_1",
      child: "link_2", axis: [0, 1, 0], limit: { lower: -1, upper: 1 } } },
    { operation: "add_joint", target: { name: "wrist", type: "revolute", parent: "link_2",
      child: "link_3", axis: [0, 1, 0], limit: { lower: -1, upper: 1 } } },
  ]);
  m = applyOperation(m, { operation: "remove_joint", target: { name: "elbow" }, cascade: true });
  assert.equal(m.joints.find((j) => j.name === "elbow"), undefined);
  assert.equal(m.joints.find((j) => j.name === "wrist"), undefined);
  assert.equal(m.links.find((l) => l.name === "link_3"), undefined);
});

test("remove_joint of missing joint throws", () => {
  assert.throws(
    () => applyOperation(base(), { operation: "remove_joint", target: { name: "nope" } }),
    /not found/
  );
});

test("unknown operation throws", () => {
  assert.throws(() => applyOperation(base(), { operation: "explode" }), /unknown operation/);
});

test("diffModels reports added and removed", () => {
  const before = base();
  const after = applyOperation(before, {
    operation: "add_joint",
    target: { name: "elbow", type: "revolute", parent: "link_1", child: "link_2" },
  });
  const changes = diffModels(before, after);
  assert.ok(changes.includes("+ joint elbow (revolute)"));
  assert.ok(changes.includes("+ link link_2"));
});
