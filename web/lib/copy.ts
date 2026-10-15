// Typed access to copy/en.json. Every piece of UI text lives there (ESLint
// react/jsx-no-literals is on, and strategist/test_web_copy.py runs the D20 rule checks over it).
// Use `copy.nav.board` for a plain string, `t("nav.board")` when the key is computed, and
// `fmt(copy.jobs.stage, { stage: 2 })` to fill {placeholders}.

import en from "@/copy/en.json";

export const copy = en;
export type Copy = typeof en;

type Leaves<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : T[K] extends object ? Leaves<T[K], `${P}${K}.`> : never;
}[keyof T & string];

/** Every dotted key that points at a string, e.g. "nav.board". */
export type CopyKey = Leaves<Copy>;

export type Vars = Record<string, string | number>;

/** Fill {name} placeholders. A missing value is left as {name}, so it shows up in review. */
export function fmt(template: string, vars: Vars = {}): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole));
}

/** The string at a dotted key, with placeholders filled. */
export function t(key: CopyKey, vars?: Vars): string {
  let node: unknown = en;
  for (const part of key.split(".")) node = (node as Record<string, unknown>)[part];
  if (typeof node !== "string") throw new Error(`copy key is not a string: ${key}`);
  return fmt(node, vars);
}

/** Split a template into text and {name} slots, for rich rendering (components/shared/rich.tsx). */
export function slots(template: string): Array<{ text: string } | { slot: string }> {
  const out: Array<{ text: string } | { slot: string }> = [];
  let last = 0;
  for (const m of template.matchAll(/\{(\w+)\}/g)) {
    if (m.index > last) out.push({ text: template.slice(last, m.index) });
    out.push({ slot: m[1] });
    last = m.index + m[0].length;
  }
  if (last < template.length) out.push({ text: template.slice(last) });
  return out;
}

/** "3 min ago" style relative time from an ISO string, using the copy's words. */
export function ago(iso: string | null | undefined, now: Date = new Date()): string | null {
  if (!iso) return null;
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return null;
  const s = Math.max(0, Math.round((now.getTime() - then.getTime()) / 1000));
  if (s < 60) return en.time.justNow;
  if (s < 3600) return fmt(en.time.minutesAgo, { n: Math.floor(s / 60) });
  if (s < 86400) return fmt(en.time.hoursAgo, { n: Math.floor(s / 3600) });
  return fmt(en.time.daysAgo, { n: Math.floor(s / 86400) });
}
