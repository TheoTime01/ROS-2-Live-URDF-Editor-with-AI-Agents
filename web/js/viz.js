// Render a robot model as a 2D kinematic-tree SVG. This is a schematic preview
// for the browser (the ROS stack drives the full RViz2 3D view). Pure function:
// takes a model, returns an SVG string, so it is unit-testable.

import { escapeHtml } from "./format.js";

const JOINT_COLOR = {
  revolute: "#4aa8ff",
  continuous: "#3ecf8e",
  prismatic: "#f2c14e",
  fixed: "#6b7787",
};

// Compute a layered layout: BFS depth from the root determines the column, and
// siblings are stacked vertically. Returns { nodes: Map<link, {x,y}>, edges }.
function layout(model) {
  const links = model.links.map((l) => l.name);
  const childOf = new Map(); // child -> {parent, joint}
  const childrenOf = new Map();
  for (const l of links) childrenOf.set(l, []);
  for (const j of model.joints) {
    if (j.parent && j.child) {
      childOf.set(j.child, { parent: j.parent, joint: j });
      if (childrenOf.has(j.parent)) childrenOf.get(j.parent).push(j.child);
    }
  }
  const roots = links.filter((l) => !childOf.has(l));

  const depth = new Map();
  const order = [];
  const queue = roots.map((r) => [r, 0]);
  const seen = new Set();
  while (queue.length) {
    const [link, d] = queue.shift();
    if (seen.has(link)) continue;
    seen.add(link);
    depth.set(link, d);
    order.push(link);
    for (const c of childrenOf.get(link) || []) queue.push([c, d + 1]);
  }
  // Any disconnected links get placed at depth 0 after roots.
  for (const l of links) if (!seen.has(l)) { depth.set(l, 0); order.push(l); }

  const rowByDepth = new Map();
  const pos = new Map();
  const colW = 150;
  const rowH = 54;
  for (const link of order) {
    const d = depth.get(link);
    const row = rowByDepth.get(d) || 0;
    rowByDepth.set(d, row + 1);
    pos.set(link, { x: 30 + d * colW, y: 30 + row * rowH, depth: d });
  }
  return { pos, childOf, order };
}

export function renderTreeSvg(model) {
  if (!model || model.links.length === 0) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="120">' +
      '<text x="20" y="60" fill="#8a99ab" font-family="sans-serif" font-size="13">No model loaded</text></svg>';
  }
  const { pos, childOf, order } = layout(model);
  let maxX = 0;
  let maxY = 0;
  for (const p of pos.values()) {
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  }
  const width = maxX + 140;
  const height = maxY + 60;

  const edges = [];
  const nodes = [];
  for (const link of order) {
    const p = pos.get(link);
    const rel = childOf.get(link);
    if (rel) {
      const pp = pos.get(rel.parent);
      const color = JOINT_COLOR[rel.joint.type] || "#6b7787";
      const midX = (pp.x + 110 + p.x) / 2;
      edges.push(
        `<path d="M ${pp.x + 110} ${pp.y + 15} C ${midX} ${pp.y + 15}, ${midX} ${p.y + 15}, ${p.x} ${p.y + 15}" ` +
          `fill="none" stroke="${color}" stroke-width="2"/>`
      );
      edges.push(
        `<text x="${midX}" y="${(pp.y + p.y) / 2 + 11}" fill="${color}" font-family="sans-serif" ` +
          `font-size="10" text-anchor="middle">${escapeHtml(rel.joint.name)}</text>`
      );
    }
    nodes.push(
      `<g><rect x="${p.x}" y="${p.y}" rx="6" width="110" height="30" fill="#1e2732" stroke="#2a3543"/>` +
        `<text x="${p.x + 55}" y="${p.y + 19}" fill="#d7e0ea" font-family="sans-serif" font-size="11.5" ` +
        `text-anchor="middle">${escapeHtml(link)}</text></g>`
    );
  }

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" ` +
    `viewBox="0 0 ${width} ${height}">` +
    edges.join("") +
    nodes.join("") +
    "</svg>"
  );
}
