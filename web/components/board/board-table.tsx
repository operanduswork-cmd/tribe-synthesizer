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
import type { MouseEvent } from "react";

import {
  COLUMNS,
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
  "h-9 border-b border-line transition-[background-color] duration-(--motion-fast) ease-(--motion-ease) last:border-b-0 pointer-coarse:h-11";
const HEAD = "h-12 border-b border-line bg-subtle/60";
const CELL = "overflow-hidden px-3 whitespace-nowrap";

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
  return <ShapeChip label={s.label} status={s.status} title={s.label} hint={shapeHint(s.status)} className="max-w-full" />;
}

/** The TRIBE yes / no, led by a mark: the brain's split cool/warm dot when a read exists, an
 *  empty dotted ring when not. The marks carry no text, so the value reads exactly yes or no. */
function TribeValue({ value }: { value: string }) {
  const yes = value === "yes";
  return (
    <span data-tribe={yes ? "yes" : "no"} className="inline-flex max-w-full items-center gap-1.5">
      {yes ? (
        <LayerDot layer="brain" className="size-2.5" />
      ) : (
        <svg aria-hidden viewBox="0 0 8 8" className="size-2.5 shrink-0 text-muted-foreground">
          <circle cx="4" cy="4" r="3.25" fill="none" strokeWidth="0.8" strokeDasharray="0.9 0.9" className="stroke-current" />
        </svg>
      )}
      <LayerValue layer="brain" className={cn(!yes && "text-muted-foreground")}>
        {value}
      </LayerValue>
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
          className="flex max-w-full min-w-0 items-baseline gap-2 text-left outline-none focus-visible:underline"
        >
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
        <span className="truncate">{label}</span>
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
      className={cn(CELL, "text-left font-medium text-muted-foreground", col.align === "end" && "text-right")}
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

  return (
    <div data-board="table" className="flex overflow-hidden rounded-xl border border-line bg-surface" onMouseLeave={() => onHover(null)}>
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
            {reels.map((reel) => (
              <tr
                key={reel.sc}
                data-line="reel"
                data-sc={reel.sc}
                aria-selected={selected === reel.sc}
                onClick={() => onPeek(reel.sc)}
                onMouseEnter={() => onHover(reel.sc)}
                className={cn(ROW, "cursor-pointer", rowState(reel.sc, selected, hovered))}
              >
                {cols.map((col) => (
                  <td key={col.id} className={cn(CELL, col.align === "end" && "text-right")}>
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
                <th scope="col" className={cn(CELL, "text-left font-medium text-muted-foreground")} title={c.tribeHint}>
                  <span className="inline-flex max-w-full flex-col items-start gap-0.5">
                    <LayerTag layer="brain" />
                    <span className="max-w-full truncate">{c.columns.tribe}</span>
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {reels.map((reel) => (
                <tr
                  key={reel.sc}
                  data-line="reel-brain"
                  data-sc={reel.sc}
                  onClick={() => onPeek(reel.sc)}
                  onMouseEnter={() => onHover(reel.sc)}
                  className={cn(ROW, "cursor-pointer", rowState(reel.sc, selected, hovered))}
                >
                  <td className={CELL}>
                    <TribeValue value={reel.cells.tribe} />
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
