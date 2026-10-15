// Small helpers for the script lab: where a check points ("beats[2].say" -> "beat 3, spoken
// line"), the copy-check span split, word counts and the command text built from inputs.
// Display only; no I/O. Client and server safe.

import { copy, fmt } from "@/lib/copy";
import type { LabPage } from "@/lib/hosted";

export type Beat = LabPage["beats"][number];
export type Hit = LabPage["hits"][number];
export type Issue = LabPage["issues"][number];
export type Variant = LabPage["variants"][number];
export type BadgeState = LabPage["badges"][number]["state"];

const BEAT_RE = /^beats\[(\d+)\](?:\.(say|on_screen|name|slot))?$/;
const VARIANT_RE = /^variants\[(\d+)\]\.line$/;

/** The beat index a check points at ("beats[2].say" -> 2), or null. */
export function beatIndex(where: string): number | null {
  const m = BEAT_RE.exec(where);
  return m ? Number(m[1]) : null;
}

/** "beats[2].say" -> "beat 3, spoken line"; "variants[0].line" -> "variant v1". */
export function whereLabel(where: string, variants: Variant[] = []): string {
  const b = BEAT_RE.exec(where);
  if (b) {
    const n = Number(b[1]) + 1;
    const field = b[2] as keyof typeof copy.lab.where.fields | undefined;
    return field ? fmt(copy.lab.where.field, { n, field: copy.lab.where.fields[field] }) : fmt(copy.lab.where.beat, { n });
  }
  const v = VARIANT_RE.exec(where);
  if (v) return fmt(copy.lab.where.variant, { id: variants[Number(v[1])]?.id ?? Number(v[1]) + 1 });
  return where;
}

/** A check message without its leading "where: " (the row already says where). */
export function stripWhere(message: string, where: string): string {
  const prefix = `${where}: `;
  return message.startsWith(prefix) ? message.slice(prefix.length) : message;
}

/** Words in a line, as a person reads them aloud (letters or digits in a run). */
export function wordCount(text: string): number {
  return (text.match(/[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu) ?? []).length;
}

/** A spoken line split around the copy-check spans that sit in it (sorted, non-overlapping). */
export function splitBySpans(text: string, spans: Array<[number, number]>): Array<{ text: string; hit: boolean }> {
  const out: Array<{ text: string; hit: boolean }> = [];
  let at = 0;
  for (const [a, z] of [...spans].sort((x, y) => x[0] - y[0])) {
    const start = Math.max(at, Math.min(a, text.length));
    const end = Math.max(start, Math.min(z, text.length));
    if (start > at) out.push({ text: text.slice(at, start), hit: false });
    if (end > start) out.push({ text: text.slice(start, end), hit: true });
    at = end;
  }
  if (at < text.length) out.push({ text: text.slice(at), hit: false });
  return out;
}

/** Free text for a /script command: one line, straight single quotes (as the offline page). */
export function cleanArg(text: string): string {
  return text.replace(/["“”]/g, "'").replace(/\s+/g, " ").trim();
}

/** Seconds as a whole number for "about 31 s". */
export const wholeSeconds = (s: number | null | undefined): number => Math.round(s ?? 0);
