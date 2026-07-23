// End-to-end browser smoke test for the web UI.
//
// Drives the real page against the static dev server with Playwright:
//   load -> visualize -> stage -> apply -> verify audit integrity -> rollback
//
// This is an OPTIONAL test: it needs Playwright + a Chromium build and the dev
// server running. It is not part of `npm test` (the pure-module unit suite),
// which has no external dependencies.
//
// Usage:
//   python3 server.py --port 8099 &
//   node test/browser-smoke.mjs            # or BASE=http://host:port node ...
//
// Requires `npm i -D playwright` (or a global install). In CI you would run
// `npx playwright install chromium` first.

import { chromium } from "playwright";

const BASE = process.env.BASE || "http://127.0.0.1:8099";

const errors = [];
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

function check(cond, msg) {
  if (!cond) throw new Error("FAILED: " + msg);
  console.log("ok - " + msg);
}

await page.goto(BASE, { waitUntil: "networkidle" });

// 1. Boots in offline mock mode.
const conn = (await page.textContent("#conn-chip")).trim();
check(/mock/i.test(conn), `boots in offline mock mode (${conn})`);

// 2. Visualization renders the sample joints.
await page.waitForSelector("#viz svg");
const viz = await page.textContent("#viz");
check(["shoulder", "elbow", "wrist"].every((j) => viz.includes(j)),
  "visualization renders shoulder/elbow/wrist");

// 3. Initial load appears in the audit trail.
check((await page.textContent("#audit-list")).includes("load"),
  "audit trail shows the initial load");

// 4. Stage a new joint via the form and apply it.
await page.selectOption("#op-type", "add_joint");
await page.fill("#op-name", "gripper");
await page.selectOption("#f-type", "revolute");
await page.fill("#f-parent", "link_3");
await page.fill("#f-child", "gripper_link");
await page.fill("#f-axis", "0 0 1");
await page.fill("#f-lower", "-0.5");
await page.fill("#f-upper", "0.5");
await page.click("#op-form button[type=submit]");
await page.waitForFunction(() => !document.getElementById("btn-apply").disabled);
check(true, "staged gripper validates and enables apply");

await page.click("#btn-apply");
await page.waitForFunction(() => document.querySelector("#viz").textContent.includes("gripper"));
check((await page.textContent("#version-list")).includes("v2"),
  "apply advances to v2 and updates the tree");

// 5. Audit integrity verifies.
await page.click('.tab[data-tab="audit"]');
await page.click("#audit-verify");
await page.waitForSelector("#audit-integrity.ok");
check(true, "audit trail integrity verifies");

// 6. Rollback removes the change.
await page.click("#btn-rollback");
await page.waitForFunction(() => !document.querySelector("#viz").textContent.includes("gripper"));
check(true, "rollback removes the gripper");

await browser.close();

if (errors.length) {
  console.error("\nCONSOLE ERRORS:\n" + errors.join("\n"));
  process.exit(1);
}
console.log("\nALL BROWSER CHECKS PASSED");
