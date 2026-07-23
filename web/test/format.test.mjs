import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formatTimestamp,
  summarizeValidation,
  severityRank,
  escapeHtml,
  shortHash,
  overallLevelClass,
} from "../js/format.js";

test("formatTimestamp renders ISO-ish UTC", () => {
  assert.equal(formatTimestamp(0), "1970-01-01 00:00:00Z");
  assert.equal(formatTimestamp(null), "—");
});

test("summarizeValidation for valid model", () => {
  assert.deepEqual(summarizeValidation({ valid: true, warnings: [] }), {
    label: "valid",
    level: "ok",
  });
});

test("summarizeValidation counts warnings and errors", () => {
  assert.equal(summarizeValidation({ valid: true, warnings: [1, 2] }).label, "valid · 2 warnings");
  assert.equal(summarizeValidation({ valid: false, errors: [1] }).label, "invalid · 1 error");
});

test("severityRank orders error > warning > info", () => {
  assert.ok(severityRank("error") > severityRank("warning"));
  assert.ok(severityRank("warning") > severityRank("info"));
});

test("escapeHtml neutralizes markup", () => {
  assert.equal(escapeHtml('<a href="x">&'), "&lt;a href=&quot;x&quot;&gt;&amp;");
});

test("shortHash truncates", () => {
  assert.equal(shortHash("abcdef1234567890", 6), "abcdef…");
  assert.equal(shortHash(""), "");
});

test("overallLevelClass maps labels", () => {
  assert.equal(overallLevelClass("ERROR"), "error");
  assert.equal(overallLevelClass("OK"), "ok");
  assert.equal(overallLevelClass("STALE"), "stale");
});
