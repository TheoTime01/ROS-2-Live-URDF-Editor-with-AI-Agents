import { test } from "node:test";
import assert from "node:assert/strict";
import { renderTreeSvg } from "../js/viz.js";
import { parseUrdf } from "../js/urdf.js";

const URDF = `<robot name="arm">
  <link name="base_link"/><link name="l1"/><link name="l2"/>
  <joint name="j1" type="revolute"><parent link="base_link"/><child link="l1"/>
    <axis xyz="0 0 1"/><limit lower="-1" upper="1"/></joint>
  <joint name="j2" type="continuous"><parent link="l1"/><child link="l2"/><axis xyz="1 0 0"/></joint>
</robot>`;

test("renderTreeSvg returns an svg with all links and joints", () => {
  const svg = renderTreeSvg(parseUrdf(URDF));
  assert.match(svg, /^<svg/);
  for (const label of ["base_link", "l1", "l2", "j1", "j2"]) {
    assert.ok(svg.includes(label), `expected ${label} in svg`);
  }
});

test("renderTreeSvg colors joints by type", () => {
  const svg = renderTreeSvg(parseUrdf(URDF));
  assert.ok(svg.includes("#4aa8ff")); // revolute
  assert.ok(svg.includes("#3ecf8e")); // continuous
});

test("renderTreeSvg handles empty model", () => {
  const svg = renderTreeSvg({ links: [], joints: [] });
  assert.match(svg, /No model loaded/);
});

test("renderTreeSvg escapes link names", () => {
  const svg = renderTreeSvg({ links: [{ name: "<script>" }], joints: [] });
  assert.ok(!svg.includes("<script>"));
  assert.ok(svg.includes("&lt;script&gt;"));
});
