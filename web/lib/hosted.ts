// The hosted page kinds: their schemas (copied from strategist/hosted_schema by
// scripts/gen-hosted.mjs), a zod parser per kind built on the contract check, and the
// generated types. Server and client safe (no I/O).

import { z } from "zod";

import board from "@/contracts/hosted_schema/board.schema.json";
import brain from "@/contracts/hosted_schema/brain.schema.json";
import lab from "@/contracts/hosted_schema/lab.schema.json";
import meta from "@/contracts/hosted_schema/meta.schema.json";
import patterns from "@/contracts/hosted_schema/patterns.schema.json";
import reel from "@/contracts/hosted_schema/reel.schema.json";
import spend from "@/contracts/hosted_schema/spend.schema.json";
import tribe from "@/contracts/hosted_schema/tribe.schema.json";
import { layerStrings, validate, type Layer, type Schema } from "@/lib/contract";
import type { PageByKind, PageKind } from "@/lib/hosted.gen";

export type { BoardPage, BrainPage, LabPage, MetaPage, PageByKind, PageKind, PatternsPage, ReelPage, SpendPage, TribePage } from "@/lib/hosted.gen";
export { PAGE_KINDS } from "@/lib/hosted.gen";

export const SCHEMAS: Record<PageKind, Schema> = { board, reel, patterns, lab, tribe, brain, meta, spend } as Record<PageKind, Schema>;

const parsers = new Map<PageKind, z.ZodType>();

/** A zod schema for one page kind. It refuses exactly what strategist.contract.check_page refuses. */
export function pageSchema<K extends PageKind>(kind: K): z.ZodType<PageByKind[K]> {
  let p = parsers.get(kind);
  if (!p) {
    const schema = SCHEMAS[kind];
    p = z.unknown().superRefine((value, ctx) => {
      for (const problem of validate(value, schema).slice(0, 20)) ctx.addIssue({ code: "custom", message: problem });
    });
    parsers.set(kind, p);
  }
  return p as z.ZodType<PageByKind[K]>;
}

export class PageError extends Error {
  constructor(
    readonly kind: PageKind,
    readonly problems: string[],
  ) {
    super(`${kind} page refused: ${problems.slice(0, 3).join("; ")}`);
    this.name = "PageError";
  }
}

/** Parse one page, or throw PageError with the contract problems. */
export function parsePage<K extends PageKind>(kind: K, value: unknown): PageByKind[K] {
  const r = pageSchema(kind).safeParse(value);
  if (!r.success) throw new PageError(kind, r.error.issues.map((i) => i.message));
  return r.data;
}

/** Every shown string in a page with its layer (for the wall checks and tests). */
export function pageLayerStrings(kind: PageKind, page: unknown): Array<[string, Layer, string]> {
  return layerStrings(page, SCHEMAS[kind]);
}
