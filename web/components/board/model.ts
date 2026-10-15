// The board's pure logic: columns, filters, saved views and sorting. No React, no I/O.
//
// Sorting uses only the sort keys the page itself lists (board.sorts, which the strategist
// checks with check_sort_key): x, plays, posted, duration, handle. Never a TRIBE field (D20).
// The TRIBE column only says whether a deep read exists (D21); it can be filtered on, never sorted
// by a brain value. The default order pins reels with a read on top by that yes/no fact alone, then
// goes longest clip first (D32); picking a sort key from the menu drops the pin.

import { copy } from "@/lib/copy";
import type { BoardPage } from "@/lib/hosted";
import type { Layer } from "@/lib/contract";

export type Board = BoardPage;
export type Reel = BoardPage["reels"][number];
export type SortSpec = BoardPage["sorts"][number];
export type SortKey = SortSpec["key"];
export type SortField = SortSpec["field"];
export type FlagKey = Reel["filter"]["flags"][number];

// ---------------------------------------------------------------- columns

export type ColumnId = "handle" | "length" | "posted" | "plays" | "x" | "hook" | "format" | "cta" | "flags" | "tribe";

export type ColumnDef = {
  id: ColumnId;
  /** The layer of the values in this column (the header shows its tag). */
  layer: Layer;
  /** The sort field a header click picks, when the page allows one. */
  sortField?: SortField;
  /** Minimum width in px (the table is fixed-layout and scrolls inside its card when narrower). */
  width: number;
  align?: "end";
  /** Shown before any Fields change. */
  defaultOn: boolean;
};

/** Main table columns, left to right. The TRIBE column is not here: it sits behind its own wall. */
export const COLUMNS: ColumnDef[] = [
  { id: "handle", layer: "ui", sortField: "handle", width: 128, defaultOn: true },
  { id: "length", layer: "facts", sortField: "duration", width: 72, defaultOn: true },
  { id: "posted", layer: "ui", sortField: "posted", width: 108, defaultOn: false },
  { id: "plays", layer: "counts", sortField: "plays", width: 88, align: "end", defaultOn: true },
  { id: "x", layer: "counts", sortField: "x", width: 132, defaultOn: true },
  { id: "hook", layer: "shape", width: 184, defaultOn: true },
  { id: "format", layer: "shape", width: 176, defaultOn: false },
  { id: "cta", layer: "shape", width: 156, defaultOn: true },
  { id: "flags", layer: "counts", width: 128, defaultOn: false },
];

export const TRIBE_COLUMN: ColumnDef = { id: "tribe", layer: "brain", width: 100, defaultOn: true };

/** Every column the Fields popover can hide (the reel column always shows). */
export const TOGGLABLE: ColumnDef[] = [...COLUMNS.filter((c) => c.id !== "handle"), TRIBE_COLUMN];

export type ColumnState = Record<ColumnId, boolean>;

export function defaultColumns(): ColumnState {
  const out = {} as ColumnState;
  for (const c of [...COLUMNS, TRIBE_COLUMN]) out[c.id] = c.defaultOn;
  out.handle = true;
  return out;
}

// ---------------------------------------------------------------- shape labels

export type ShapeCell = { label: string; status: "suggested" | "accepted" } | null;

const SUGGESTED = " (suggested)";
const NOT_TAGGED = "not tagged";

/** A shape cell as the strategist writes it: "list tease (suggested)", "cold open question" or "not tagged". */
export function shapeCell(text: string): ShapeCell {
  const t = (text ?? "").trim();
  if (!t || t === NOT_TAGGED) return null;
  if (t.endsWith(SUGGESTED)) return { label: t.slice(0, -SUGGESTED.length), status: "suggested" };
  return { label: t, status: "accepted" };
}

export function hasSuggested(r: Reel): boolean {
  return [r.cells.hook, r.cells.format, r.cells.cta].some((c) => shapeCell(c)?.status === "suggested");
}

/** A board shape chip's short status for screen readers and hover (D30, less text): "Claude
 *  suggested" or "Accepted". The outline (suggested) or the fill (accepted) shows it to the eye. */
export function shapeHint(status: NonNullable<ShapeCell>["status"]): string {
  return status === "suggested" ? copy.shape.suggested : copy.shape.accepted;
}

// ---------------------------------------------------------------- flags

/**
 * A flag's head, for the table and the cards: its words before the first " · ", ": " or ", "
 * ("under 2x · taste, not proof" -> "under 2x", "gated CTA, guessed from comments" -> "gated
 * CTA"). The full label stays in the hover text, the Filters menu and the peek (D30).
 */
export function flagHead(label: string): string {
  return label.split(/ · |: |, /)[0] || label;
}

// ---------------------------------------------------------------- x own median

/**
 * The "x own median" cell as the strategist writes it (fmt_x(x) + " (size)"), split into the
 * multiplier and its baseline note: "4.9x (18 reels)" -> { mult: "4.9x", note: "(18 reels)" }.
 * "no x yet" has no note. Display only: sorting uses r.sort.x, never this string.
 */
export function splitX(text: string): { mult: string; note: string } {
  const i = text.indexOf(" (");
  if (i < 0) return { mult: text, note: "" };
  return { mult: text.slice(0, i), note: text.slice(i + 1) };
}

// ---------------------------------------------------------------- filters

/** At most one value per field. Fields are ANDed. */
export type Filters = {
  hook?: string;
  format?: string;
  length?: string;
  flag?: FlagKey;
  twoX?: true;
  labels?: "suggested";
  tribe?: "yes" | "no";
};

export type FilterField = keyof Filters;

/** The order the Filters menu and the chips use. TRIBE last, behind the wall. */
export const FILTER_FIELDS: FilterField[] = ["hook", "format", "length", "flag", "twoX", "labels", "tribe"];

/** The layer of each filter's value, for its chip. */
export const FILTER_LAYER: Record<FilterField, Layer> = {
  hook: "shape",
  format: "shape",
  length: "facts",
  flag: "counts",
  twoX: "counts",
  labels: "shape",
  tribe: "brain",
};

export function matches(r: Reel, f: Filters): boolean {
  if (f.hook !== undefined && r.filter.hook !== f.hook) return false;
  if (f.format !== undefined && r.filter.format !== f.format) return false;
  if (f.length !== undefined && r.filter.length !== f.length) return false;
  if (f.flag !== undefined && !r.filter.flags.includes(f.flag)) return false;
  if (f.twoX && !r.filter.two_x) return false;
  if (f.labels === "suggested" && !hasSuggested(r)) return false;
  if (f.tribe !== undefined && r.filter.tribe !== (f.tribe === "yes")) return false;
  return true;
}

export function activeFilters(f: Filters): FilterField[] {
  return FILTER_FIELDS.filter((k) => f[k] !== undefined);
}

export function sameFilters(a: Filters, b: Filters): boolean {
  return FILTER_FIELDS.every((k) => a[k] === b[k]);
}

// ---------------------------------------------------------------- sorting

/** The page's own sort options. Anything else (and any TRIBE field) is never offered. */
export function sortOptions(board: Board): SortSpec[] {
  return board.sorts.filter((s) => !/tribe|brain/i.test(s.key) && !/tribe|brain/i.test(s.field));
}

export function sortSpec(board: Board, key: SortKey): SortSpec {
  const opts = sortOptions(board);
  return opts.find((s) => s.key === key) ?? opts.find((s) => s.key === board.default_sort) ?? opts[0];
}

/** The yes/no the TRIBE column shows: a read exists. Existence only, never a brain value (D32). */
export function hasRead(r: Reel): boolean {
  return r.cells.tribe === "yes";
}

/** Sorted copy. Missing values go last whatever the direction; ties keep the page order. With
 *  `pin`, reels that have a read come first (by the yes/no fact only), each group sorted by spec. */
export function sortReels(reels: Reel[], spec: SortSpec | undefined, pin = false): Reel[] {
  if (!spec && !pin) return reels.slice();
  const dir = spec?.desc ? -1 : 1;
  return reels
    .map((r, i) => ({ r, i }))
    .sort((a, b) => {
      if (pin && hasRead(a.r) !== hasRead(b.r)) return hasRead(a.r) ? -1 : 1;
      if (!spec) return a.i - b.i;
      const va = a.r.sort[spec.field];
      const vb = b.r.sort[spec.field];
      if (va === null && vb === null) return a.i - b.i;
      if (va === null) return 1;
      if (vb === null) return -1;
      const c = typeof va === "string" ? va.localeCompare(String(vb)) : va - (vb as number);
      return c === 0 ? a.i - b.i : c * dir;
    })
    .map(({ r }) => r);
}

// ---------------------------------------------------------------- saved views

export type ViewId = "all" | "twoX" | "review";
/** `pin`: reels with a read lead (D32). Only the default order pins; any menu pick clears it. */
export type ViewState = { filters: Filters; sort: SortKey; pin: boolean };

export const VIEW_IDS: ViewId[] = ["all", "twoX", "review"];

export function viewState(board: Board, id: ViewId): ViewState {
  // Default: read reels first, then longest clip first (D32), by the page's own duration key.
  const sort = sortSpec(board, "-duration").key;
  if (id === "twoX") return { filters: { twoX: true }, sort: sortSpec(board, "-x").key, pin: false };
  if (id === "review") return { filters: { labels: "suggested" }, sort, pin: true };
  return { filters: {}, sort, pin: true };
}

/** The saved view the current state equals, or null for a custom view. */
export function currentView(board: Board, s: ViewState): ViewId | null {
  return VIEW_IDS.find((id) => {
    const v = viewState(board, id);
    return v.sort === s.sort && v.pin === s.pin && sameFilters(v.filters, s.filters);
  }) ?? null;
}

/** The creator rows for one handle (baseline size, median, what was left out). */
export function creatorItems(board: Board, handle: string): string[] {
  return board.creators.find((c) => c.handle === handle)?.items ?? [];
}

export function reelHref(sc: string): string {
  return `/reels/${encodeURIComponent(sc)}`;
}
