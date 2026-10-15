"use client";

// Reels as cards: the phone layout under 768px and the grid view on a laptop (Binance Data
// Center reference; no footer row, as in Airtable's cards). Each card: the handle, the posted
// date (the word "posted" in its hover text only, D30), the length and a chevron on one title
// line, the shape chips, the counts inline ("61,200 plays · 4.9x (18 reels)"), then the flags
// by their heads ("under 2x"; the full labels are in the peek). The handle button stretches over the
// whole card (its ::after), so a tap anywhere on the card opens the peek. No thumbnails
// (stills stay on the laptop).
//
// Every line is its own data-line. No TRIBE value on a card: a card holds counts, so the TRIBE
// yes/no stays in the table's own column behind its wall, the filter and the reel page (D20).
// Hover darkens the card's border only (never a lift or a move); the selected card stays indigo.

import { ChevronRightIcon } from "lucide-react";

import { FlagList } from "@/components/board/flag-list";
import { shapeCell, shapeHint, splitX, type ColumnState, type Reel } from "@/components/board/model";
import { LayerValue } from "@/components/shared/layer-value";
import { ShapeChip } from "@/components/shared/shape-chip";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

const c = copy.board;

function Shapes({ reel, columns }: { reel: Reel; columns: ColumnState }) {
  const fields = (["hook", "format", "cta"] as const).filter((f) => columns[f]);
  const chips = fields.map((f) => ({ f, s: shapeCell(reel.cells[f]) }));
  if (!chips.length) return null;
  return (
    <div data-line="shape" className="flex flex-wrap gap-1.5">
      {chips.map(({ f, s }) =>
        s ? (
          <ShapeChip key={f} field={c.peek[f]} label={s.label} status={s.status} hint={shapeHint(s.status)} />
        ) : (
          <LayerValue key={f} layer="shape" className="inline-flex h-6 items-center gap-1.5 rounded-md border border-dashed border-line px-2 text-ui text-muted-foreground">
            <span className="font-mono text-mono opacity-70">{c.peek[f]}</span>
            <span>{c.notTagged}</span>
          </LayerValue>
        ),
      )}
    </div>
  );
}

/** "4.9x (18 reels)": the multiplier in weight, its baseline note muted (as "61,200 plays"). */
function XValue({ text }: { text: string }) {
  const { mult } = splitX(text);
  return (
    <span className="inline-flex items-baseline gap-1" title={text}>
      <LayerValue layer="counts" className="font-semibold">
        {mult}
      </LayerValue>
    </span>
  );
}

export function BoardCards({
  reels,
  columns,
  selected,
  onPeek,
  className,
}: {
  reels: Reel[];
  columns: ColumnState;
  selected: string | null;
  onPeek: (sc: string) => void;
  className?: string;
}) {
  return (
    <ul data-board="cards" className={cn("grid gap-3 md:grid-cols-[repeat(auto-fill,minmax(300px,1fr))]", className)}>
      {reels.map((reel) => (
        <li
          key={reel.sc}
          data-sc={reel.sc}
          className={cn(
            "relative flex min-w-0 flex-col rounded-xl border bg-surface transition-[border-color] duration-(--motion-fast) ease-(--motion-ease)",
            selected === reel.sc ? "border-indigo-accent" : "border-line hover:border-foreground/25",
          )}
        >
          <div className="flex flex-col gap-2 px-4 py-3">
            <div data-line="title" className="flex items-baseline gap-2">
              {/* The card's only button: its ::after covers the whole card. No tap-target here
                  (it sets position: relative on touch, which would shrink the ::after back to
                  the button), and nothing else in the card is positioned or interactive. */}
              <button
                type="button"
                onClick={() => onPeek(reel.sc)}
                aria-label={fmt(c.peekAt, { handle: reel.handle })}
                className="flex min-w-0 flex-1 text-left text-sm font-semibold outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:outline-2 focus-visible:after:outline-indigo-accent"
              >
                <LayerValue layer="ui" className="truncate">
                  {reel.handle}
                </LayerValue>
              </button>
              <LayerValue layer="ui" title={fmt(c.card.posted, { date: reel.cells.posted })} className="shrink-0 font-mono text-mono text-muted-foreground">
                {reel.cells.posted}
              </LayerValue>
              {columns["length"] ? <LayerValue layer="facts" className="shrink-0 text-muted-foreground">{reel.cells.length}</LayerValue> : null}
              <ChevronRightIcon className="size-4 shrink-0 self-center text-muted-foreground" aria-hidden />
            </div>

            <Shapes reel={reel} columns={columns} />

            {columns.plays || columns.x ? (
              <div data-line="counts" className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-ui">
                {columns.plays ? (
                  <span className="inline-flex items-baseline gap-1">
                    <LayerValue layer="counts" className="font-semibold">
                      {reel.cells.plays}
                    </LayerValue>
                    <LayerValue layer="counts" className="text-muted-foreground">
                      {c.card.plays}
                    </LayerValue>
                  </span>
                ) : null}
                {columns.x ? <XValue text={reel.cells.x} /> : null}
              </div>
            ) : null}

            {columns.flags && reel.badges.length ? (
              <div data-line="flags" className="flex">
                <FlagList reel={reel} short />
              </div>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
