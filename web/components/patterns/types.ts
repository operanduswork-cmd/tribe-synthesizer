// Shared types for the patterns screen, taken from the generated hosted page type.

import type { PatternsPage } from "@/lib/hosted";

export type Pattern = PatternsPage["patterns"][number];
export type PatternKind = Pattern["kind"];
export type PatternTab = PatternsPage["tabs"][number];
export type LabelFilter = "all" | "accepted" | "suggested";
export type KindFilter = "all" | PatternKind;

/** The fixed catalog order (strategist/render.py PATTERN_TABS). Never sorted by a count. */
export const KIND_ORDER: PatternKind[] = ["hook", "structure", "cta", "format"];

/** A pattern name cut for the row (round 4 text cut): at most 3 words and 24 characters, an
 *  ellipsis when cut. The full name is the chip's hover text and the row's button title. */
export function shortLabel(label: string): string {
  const words = label.split(/\s+/).filter((w) => w && !/^[→>·|/-]+$/.test(w));
  if (words.length <= 3 && label.trim().length <= 24) return label.trim();
  let out = words.slice(0, 3).join(" ");
  if (out.length > 24) out = out.slice(0, 24).replace(/\s+\S*$/, "") || out.slice(0, 24);
  return `${out}…`;
}

/** One group size for the legend when every compared pattern shares it, else null. */
export function groupSizes(patterns: Pattern[]): { o: number | null; m: number | null } {
  const os = new Set<number>();
  const ms = new Set<number>();
  for (const p of patterns) {
    if (!p.bars) continue;
    os.add(p.bars.o[1]);
    ms.add(p.bars.m[1]);
  }
  return { o: os.size === 1 ? [...os][0] : null, m: ms.size === 1 ? [...ms][0] : null };
}
