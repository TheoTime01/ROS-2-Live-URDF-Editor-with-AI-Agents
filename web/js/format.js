// Small pure formatting/derivation helpers shared by the UI. Kept separate from
// DOM code so they can be unit-tested with `node --test`.

export function formatTimestamp(ts) {
  if (ts == null) return "—";
  const d = new Date(ts * 1000);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

export function severityRank(severity) {
  return { error: 3, warning: 2, info: 1 }[severity] || 0;
}

// Collapse a ValidationResult into a one-line status used by the header badge.
export function summarizeValidation(result) {
  if (!result) return { label: "unknown", level: "info" };
  if (result.valid) {
    const w = result.warnings ? result.warnings.length : 0;
    return {
      label: w ? `valid · ${w} warning${w === 1 ? "" : "s"}` : "valid",
      level: w ? "warning" : "ok",
    };
  }
  const n = result.errors ? result.errors.length : 0;
  return { label: `invalid · ${n} error${n === 1 ? "" : "s"}`, level: "error" };
}

export function overallLevelClass(label) {
  return (
    { OK: "ok", WARN: "warning", ERROR: "error", STALE: "stale" }[label] || "info"
  );
}

// Escape text for safe insertion into HTML.
export function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Short hash for display (first n hex chars + ellipsis).
export function shortHash(hex, n = 8) {
  if (!hex) return "";
  return hex.length > n ? hex.slice(0, n) + "…" : hex;
}
