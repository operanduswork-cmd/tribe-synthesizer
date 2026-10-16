"use client";

// The board table (Neon tables reference): dense 36px rows (44px on touch), the layer tag in
// mono next to each column name (COUNT / FACT / SHAPE), led by the layer's colour dot (Linear's
// label dots), sortable headers only where the page allows that sort. No rank or row numbers.
// Hover changes the row background only (Neon, Attio), with a short fade; rows never move or grow.
//
// The TRIBE column (BRAIN) is a separate one-column table to the right, behind a dotted wall,
// with rows of the same height: a play count and a brain value never share a row (D20). It
// only says yes or no (D21), its header is never clickable and no brain value sorts anything, and the
// Fields popover can hide it. The default order pins "yes" reels on top by that fact alone (D32). "yes" leads
// with the brain's split cool/warm dot and "no" with an empty dotted ring (Attio's dot + word
// status cells); the text stays exactly yes / no, and the dot is identity, never a status.

import { ArrowDownIcon, ArrowUpIcon } from "lucide-react";
import type { CSSProperties, MouseEvent } from "react";

import {
  COLUMNS,
  hasRead,
  TRIBE_COLUMN,
  shapeCell,
  shapeHint,
  splitX,
  type Board,
  type ColumnDef,
  type ColumnState,
  type Reel,
  type SortField,
  type SortKey,
  type SortSpec,
} from "@/components/board/model";
import { FlagList } from "@/components/board/flag-list";
import { LayerDot, LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { ShapeChip } from "@/components/shared/shape-chip";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

const c = copy.board;

const ROW =
  "row-in h-9 border-b border-line transition-[background-color] duration-(--motion-fast) ease-(--motion-ease) last:border-b-0 pointer-coarse:h-11";
const HEAD = "h-12 border-b border-line";
const CELL = "overflow-hidden px-3 whitespace-nowrap";
const TH = "head-glass bg-subtle/70";

// Sleek pass (round 7): proportional bars under Length (facts) and x own median (counts), each on
// its own scale (the longest / largest visible), never a brain value (D20). Monogram hue is a
// stable hash of the handle. Row stagger index is capped so long boards do not wait.
type Scales = { length: number; x: number };

function hueOf(handle: string): number {
  let h = 0;
  for (const ch of handle) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

function initials(handle: string): string {
  const parts = handle.replace(/^@/, "").split(/[^A-Za-z0-9]+/).filter(Boolean);
  const s = parts.length > 1 ? parts[0][0] + parts[1][0] : (parts[0] ?? "?").slice(0, 2);
  return s.toUpperCase();
}

function frac(v: number | null | undefined, max: number): number {
  return typeof v === "number" && max > 0 ? Math.max(0, Math.min(1, v / max)) : 0;
}

type TableProps = {
  board: Board;
  reels: Reel[];
  columns: ColumnState;
  sort: SortSpec | undefined;
  onSort: (key: SortKey) => void;
  selected: string | null;
  hovered: string | null;
  onHover: (sc: string | null) => void;
  onPeek: (sc: string) => void;
};

function rowState(sc: string, selected: string | null, hovered: string | null) {
  return cn(selected === sc ? "bg-indigo-soft" : hovered === sc ? "bg-subtle" : "");
}

function Shape({ text }: { text: string }) {
  const s = shapeCell(text);
  if (!s) {
    return (
      <LayerValue layer="shape" className="text-muted-foreground">
        {c.notTagged}
      </LayerValue>
    );
  }
  return <ShapeChip label={s.label} status={s.status} title={s.label} hint={shapeHint(s.status)} className="chip-glow max-w-full" />;
}

/** The TRIBE cell always says "yes" (his override, D32), led by the brain's filled split cool/warm
 *  dot on EVERY row (his call, 16 Oct: the unread rows look the same as the read ones). data-tribe
 *  carries the real flag, never the label; the pin and the filter use hasRead, not this mark. */
function TribeValue({ read }: { read: boolean }) {
  return (
    <span data-tribe={read ? "yes" : "no"} className="inline-flex max-w-full items-center gap-1.5">
      <LayerDot layer="brain" className={cn("size-2.5", read && "dot-pulse")} />
      <LayerValue layer="brain">{c.filters.yes}</LayerValue>
    </span>
  );
}

function Cell({ col, reel, onPeek }: { col: ColumnDef; reel: Reel; onPeek: (sc: string) => void }) {
  const r = reel.cells;
  switch (col.id) {
    case "handle":
      return (
        <button
          type="button"
          onClick={(e: MouseEvent) => {
            e.stopPropagation();
            onPeek(reel.sc);
          }}
          aria-label={fmt(c.peekAt, { handle: reel.handle })}
          className="flex max-w-full min-w-0 items-center gap-2 text-left outline-none focus-visible:underline"
        >
          <span aria-hidden className="monogram" style={{ "--h": hueOf(reel.handle) } as CSSProperties}>
            {initials(reel.handle)}
          </span>
          <LayerValue layer="ui" className="truncate font-medium">
            {reel.handle}
          </LayerValue>
        </button>
      );
    case "length":
      return <LayerValue layer="facts">{r.length}</LayerValue>;
    case "posted":
      return (
        <LayerValue layer="ui" className="font-mono text-mono text-muted-foreground">
          {r.posted}
        </LayerValue>
      );
    case "plays":
      return (
        <LayerValue layer="counts" className="font-medium">
          {r.plays}
        </LayerValue>
      );
    case "x": {
      // The multiplier right-aligned in its own slot (decimals line up), the baseline note muted.
      // The baseline note "(18 reels)" is no sub-text in the row (round 4): it is the hover text.
      const { mult } = splitX(r.x);
      return (
        <LayerValue layer="counts" className="flex min-w-0 items-baseline gap-2" title={r.x}>
          <LayerValue layer="counts" className="min-w-12 shrink-0 text-right font-medium">
            {mult}
          </LayerValue>
        </LayerValue>
      );
    }
    case "hook":
      return <Shape text={r.hook} />;
    case "format":
      return <Shape text={r.format} />;
    case "cta":
      return <Shape text={r.cta} />;
    case "flags":
      return <FlagList reel={reel} max={1} short />;
    default:
      return null;
  }
}

function HeaderCell({ col, sort, onSort, board }: { col: ColumnDef; sort: SortSpec | undefined; onSort: (k: SortKey) => void; board: Board }) {
  const label = c.columns[col.id];
  const option = col.sortField ? board.sorts.find((s) => s.field === (col.sortField as SortField)) : undefined;
  const active = option && sort?.field === option.field;
  // Two lines (Neon shows the type next to the name; here the layer tag sits above it so narrow
  // columns keep their full name): the mono tag, then the name and the sort arrow.
  const inner = (
    <>
      {col.layer !== "ui" ? <LayerTag layer={col.layer} /> : <span aria-hidden className="h-4" />}
      <span className={cn("inline-flex max-w-full items-center gap-1", col.align === "end" && "flex-row-reverse")}>
        <span className="head-label truncate">{label}</span>
        {active ? (
          sort?.desc ? (
            <ArrowDownIcon className="size-3 shrink-0" aria-hidden />
          ) : (
            <ArrowUpIcon className="size-3 shrink-0" aria-hidden />
          )
        ) : null}
      </span>
    </>
  );
  const stack = cn("inline-flex max-w-full flex-col gap-0.5", col.align === "end" ? "items-end" : "items-start");
  return (
    <th
      scope="col"
      aria-sort={active ? (sort?.desc ? "descending" : "ascending") : undefined}
      className={cn(CELL, TH, "text-left font-medium text-muted-foreground", col.align === "end" && "text-right")}
    >
      {option ? (
        <button
          type="button"
          onClick={() => onSort(option.key)}
          title={fmt(c.sort.header, { label: option.label })}
          className={cn(stack, "transition-colors duration-(--motion-fast) hover:text-foreground", active && "text-foreground")}
        >
          {inner}
        </button>
      ) : (
        <span className={stack}>{inner}</span>
      )}
    </th>
  );
}

export function BoardTable({ board, reels, columns, sort, onSort, selected, hovered, onHover, onPeek }: TableProps) {
  const cols = COLUMNS.filter((col) => columns[col.id]);
  const minWidth = cols.reduce((sum, col) => sum + col.width, 0);
  const showTribe = columns.tribe;

  const scales: Scales = {
    length: Math.max(0, ...reels.map((r) => r.sort.duration ?? 0)),
    x: Math.max(0, ...reels.map((r) => r.sort.x ?? 0)),
  };
  const barOf = (col: ColumnDef, reel: Reel): CSSProperties | undefined =>
    col.id === "length"
      ? ({ "--bar-w": frac(reel.sort.duration, scales.length), "--bar-color": "var(--bar-facts)" } as CSSProperties)
      : col.id === "x"
        ? ({ "--bar-w": frac(reel.sort.x, scales.x), "--bar-color": "var(--bar-counts)" } as CSSProperties)
        : undefined;

  return (
    <div data-board="table" className="sleek-card flex overflow-hidden rounded-xl" onMouseLeave={() => onHover(null)}>
      <div className="min-w-0 flex-1 overflow-x-auto">
        <table className="w-full table-fixed border-collapse text-ui" style={{ minWidth }}>
          <colgroup>
            {cols.map((col) => (
              <col key={col.id} style={{ width: col.width }} />
            ))}
          </colgroup>
          <thead>
            <tr data-line="head" className={HEAD}>
              {cols.map((col) => (
                <HeaderCell key={col.id} col={col} sort={sort} onSort={onSort} board={board} />
              ))}
            </tr>
          </thead>
          <tbody>
            {reels.map((reel, i) => (
              <tr
                key={reel.sc}
                style={{ "--i": Math.min(i, 14) } as CSSProperties}
                data-line="reel"
                data-sc={reel.sc}
                aria-selected={selected === reel.sc}
                onClick={() => onPeek(reel.sc)}
                onMouseEnter={() => onHover(reel.sc)}
                className={cn(ROW, "row-accent cursor-pointer", rowState(reel.sc, selected, hovered))}
              >
                {cols.map((col) => (
                  <td
                    key={col.id}
                    style={barOf(col, reel)}
                    className={cn(CELL, col.align === "end" && "text-right", (col.id === "length" || col.id === "x") && "value-bar", col.id === "x" && "value-bar-end")}
                  >
                    <Cell col={col} reel={reel} onPeek={onPeek} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showTribe ? (
        <div data-board="tribe-column" className="shrink-0 border-l border-dotted border-muted-foreground/50" style={{ width: TRIBE_COLUMN.width }}>
          <table className="w-full table-fixed border-collapse text-ui" aria-label={c.tribeTable}>
            <thead>
              <tr data-line="head-brain" className={HEAD}>
                <th scope="col" className={cn(CELL, TH, "text-left font-medium text-muted-foreground")} title={c.tribeHint}>
                  <span className="inline-flex max-w-full flex-col items-start gap-0.5">
                    <LayerTag layer="brain" />
                    <span className="head-label max-w-full truncate">{c.columns.tribe}</span>
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {reels.map((reel, i) => (
                <tr
                  key={reel.sc}
                  style={{ "--i": Math.min(i, 14) } as CSSProperties}
                  data-line="reel-brain"
                  data-sc={reel.sc}
                  onClick={() => onPeek(reel.sc)}
                  onMouseEnter={() => onHover(reel.sc)}
                  className={cn(ROW, "cursor-pointer", rowState(reel.sc, selected, hovered))}
                >
                  <td className={CELL}>
                    <TribeValue read={hasRead(reel)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
