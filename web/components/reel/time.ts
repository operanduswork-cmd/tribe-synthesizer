// Time helpers for the reel screen, ported from dashboard/template.html (fmt, fmtRange, band)
// so the site and the offline report page read the same seconds the same way. Pure functions,
// safe on the server and in the browser.

export const LINE_KEYS = ["seeing", "hearing", "language", "attention"] as const;
export type LineKey = (typeof LINE_KEYS)[number];

export type Band = "wellAbove" | "above" | "near" | "below" | "wellBelow" | "none";

const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));

/** "m:ss" from seconds, floored (the template's fmt). */
export function clock(t: number): string {
  const s = Math.max(0, Math.floor((t || 0) + 1e-6));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r < 10 ? "0" : ""}${r}`;
}

/** The closed range of whole seconds a span [a, b) touches, as the clock shows them
 *  (the template's fmtRange and render.py page_range): [30, 34) -> 0:30-0:33, [20, 21) -> 0:20. */
export function clockRange(a: number, b: number, lastSec: number): string {
  const fa = clamp(Math.floor((a || 0) + 1e-6), 0, lastSec);
  const fb = clamp(Math.ceil((b || 0) - 1e-6) - 1, fa, lastSec);
  return fb === fa ? clock(fa) : `${clock(fa)}-${clock(fb)}`;
}

const CHIP_RE = /^(\d{1,2}):([0-5]\d)(?:-(\d{1,2}):([0-5]\d))?$/;

/** A time chip ("0:03-0:11" or "0:20") as a span of whole seconds [start, end). */
export function parseChip(chip: string | null | undefined): { start: number; end: number } | null {
  const m = CHIP_RE.exec(chip ?? "");
  if (!m) return null;
  const start = Number(m[1]) * 60 + Number(m[2]);
  const last = m[3] === undefined ? start : Number(m[3]) * 60 + Number(m[4]);
  return { start, end: Math.max(start, last) + 1 };
}

/** Where a display_z value sits against this reel's own average (the template's band). */
export function band(z: number | null | undefined): Band {
  if (typeof z !== "number" || !Number.isFinite(z)) return "none";
  if (z >= 1) return "wellAbove";
  if (z >= 0.5) return "above";
  if (z > -0.5) return "near";
  if (z > -1) return "below";
  return "wellBelow";
}

/** The shared y range for the lanes: at least 2.5, rounded up to a half, plus a margin
 *  (the template's yMax), so every lane is drawn on the same scale. */
export function laneYMax(lines: Array<Array<number | null>>): number {
  let y = 2.5;
  for (const zs of lines) for (const z of zs) if (typeof z === "number" && Number.isFinite(z)) y = Math.max(y, Math.abs(z));
  return Math.ceil(y * 2) / 2 + 0.25;
}

/** A percentage of the time axis, for absolutely placed marks. */
export function pct(t: number, tEnd: number): number {
  return clamp((t / Math.max(tEnd, 1e-6)) * 100, 0, 100);
}
