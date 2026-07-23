// Apply structured EditOperation objects to a URDF model (client-side mirror of
// `urdf_live_editor/model/edit_ops.py`). Every function is pure: it returns a
// new model and never mutates its input, so undo/redo and staged candidates are
// trivial. Supported operations match the README:
//   add_link, add_joint, update_joint, remove_joint, set_joint_limit,
//   set_joint_axis, rename

function clone(model) {
  return JSON.parse(JSON.stringify(model));
}

function findJoint(model, name) {
  return model.joints.find((j) => j.name === name);
}

// Apply a single EditOperation, returning a new model. Throws on structurally
// impossible operations (e.g. removing a joint that doesn't exist); semantic
// validity is checked separately by validateModel.
export function applyOperation(model, op) {
  const next = clone(model);
  const t = op.target || {};
  switch (op.operation) {
    case "add_link": {
      if (!t.name) throw new Error("add_link requires target.name");
      if (next.links.some((l) => l.name === t.name))
        throw new Error(`link '${t.name}' already exists`);
      next.links.push({ name: t.name });
      return next;
    }
    case "add_joint": {
      if (!t.name) throw new Error("add_joint requires target.name");
      if (next.joints.some((j) => j.name === t.name))
        throw new Error(`joint '${t.name}' already exists`);
      next.joints.push({
        name: t.name,
        type: (t.type || "revolute").toLowerCase(),
        parent: t.parent || null,
        child: t.child || null,
        axis: t.axis || null,
        limit: t.limit || null,
        origin: t.origin || null,
      });
      // Auto-create the child link if requested and absent (a common convenience).
      if (t.child && !next.links.some((l) => l.name === t.child)) {
        next.links.push({ name: t.child });
      }
      return next;
    }
    case "update_joint": {
      const j = findJoint(next, t.name);
      if (!j) throw new Error(`joint '${t.name}' not found`);
      for (const key of ["type", "parent", "child", "axis", "limit", "origin"]) {
        if (key in t) j[key] = t[key];
      }
      if (j.type) j.type = j.type.toLowerCase();
      return next;
    }
    case "remove_joint": {
      const idx = next.joints.findIndex((j) => j.name === t.name);
      if (idx === -1) throw new Error(`joint '${t.name}' not found`);
      const removed = next.joints[idx];
      next.joints.splice(idx, 1);
      // Optionally cascade: remove the subtree rooted at the child link.
      if (op.cascade && removed.child) {
        removeSubtree(next, removed.child);
      }
      return next;
    }
    case "set_joint_limit": {
      const j = findJoint(next, t.name);
      if (!j) throw new Error(`joint '${t.name}' not found`);
      j.limit = t.limit === null ? null : { ...(j.limit || {}), ...(t.limit || {}) };
      return next;
    }
    case "set_joint_axis": {
      const j = findJoint(next, t.name);
      if (!j) throw new Error(`joint '${t.name}' not found`);
      j.axis = t.axis || null;
      return next;
    }
    case "rename": {
      if (!t.name || !t.new_name) throw new Error("rename requires target.name and target.new_name");
      renameEntity(next, t.name, t.new_name);
      return next;
    }
    default:
      throw new Error(`unknown operation '${op.operation}'`);
  }
}

function removeSubtree(model, rootLink) {
  const toVisit = [rootLink];
  const linksToRemove = new Set();
  while (toVisit.length) {
    const link = toVisit.pop();
    linksToRemove.add(link);
    for (const j of model.joints) {
      if (j.parent === link && j.child) toVisit.push(j.child);
    }
  }
  model.links = model.links.filter((l) => !linksToRemove.has(l.name));
  model.joints = model.joints.filter(
    (j) => !linksToRemove.has(j.parent) && !linksToRemove.has(j.child)
  );
}

function renameEntity(model, oldName, newName) {
  let touched = false;
  for (const l of model.links) {
    if (l.name === oldName) {
      l.name = newName;
      touched = true;
    }
  }
  for (const j of model.joints) {
    if (j.name === oldName) {
      j.name = newName;
      touched = true;
    }
    if (j.parent === oldName) j.parent = newName;
    if (j.child === oldName) j.child = newName;
  }
  if (!touched) throw new Error(`nothing named '${oldName}' to rename`);
}

// Apply a batch of operations in order, returning the final model. Any failure
// throws and the caller keeps the original (staging is all-or-nothing).
export function applyOperations(model, ops) {
  return ops.reduce((acc, op) => applyOperation(acc, op), model);
}

// A structured, order-independent diff between two models, suitable for the
// audit trail and the UI "what changed" panel.
export function diffModels(before, after) {
  const changes = [];
  const beforeLinks = new Set(before.links.map((l) => l.name));
  const afterLinks = new Set(after.links.map((l) => l.name));
  for (const name of afterLinks) if (!beforeLinks.has(name)) changes.push(`+ link ${name}`);
  for (const name of beforeLinks) if (!afterLinks.has(name)) changes.push(`- link ${name}`);

  const beforeJ = new Map(before.joints.map((j) => [j.name, j]));
  const afterJ = new Map(after.joints.map((j) => [j.name, j]));
  for (const [name, j] of afterJ) {
    if (!beforeJ.has(name)) {
      changes.push(`+ joint ${name} (${j.type})`);
    } else if (JSON.stringify(beforeJ.get(name)) !== JSON.stringify(j)) {
      changes.push(`~ joint ${name}`);
    }
  }
  for (const name of beforeJ.keys()) if (!afterJ.has(name)) changes.push(`- joint ${name}`);
  return changes;
}
