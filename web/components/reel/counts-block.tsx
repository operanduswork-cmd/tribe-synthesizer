// Counts for one reel, in their own block and their own chart (D20: never on a line, chart or
// total with the brain layer). The chart is the board's peer strip turned into a dot plot
// (Linktree reference): the creator's own reels as small solid dots, the own median as a
// dashed line labelled at the right edge, this reel as a filled dot. Log scale, no numbers on
// the axis (the strip text above the card carries the numbers).
// Colour: only "this reel" wears the counts teal (one highlighted mark, the rest muted context;
// teal is the counts layer, never "good"); it keeps its direct label, so it never relies on
// colour alone. The plot never animates (counts are snapshots; globals.css stops it too).

import { InfoHint } from "@/components/shared/info-hint";
import { LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { copy, fmt } from "@/lib/copy";
import type { BoardPage } from "@/lib/hosted";
import { cn } from "@/lib/utils";

import { DiscountForm } from "./discount-form";
import { SwatchLegend } from "./hint-popover";
import { CARD_CLASS } from "./reel-card";

const C = copy.reel.counts;

type BoardRow = BoardPage["reels"][number];
type Peer = NonNullable<BoardRow["peer"]>;

/** Top as a percentage, with room so dots at 0 and 1 are not clipped. */
const top = (v: number) => 10 + (1 - Math.min(1, Math.max(0, v))) * 80;
const OWN_FROM = 3;
const OWN_TO = 68;
const ME_AT = 80;

function CountsChart({ peer }: { peer: Peer }) {
  const n = peer.ticks.length;
  const meAbove = peer.me >= peer.median;
  return (
    <figure data-chart="counts" className="flex flex-col gap-2">
      <div role="img" aria-label={C.chartLabel} className="relative h-32 border-y border-line">
        <div
          data-layer="counts"
          data-median
          className="absolute inset-x-0 border-t border-dashed border-muted-foreground"
          style={{ top: `${top(peer.median)}%` }}
        >
          <span className="absolute right-0 bottom-0.5 text-[10px] leading-3 text-muted-foreground">{C.median}</span>
        </div>
        {peer.ticks.map((v, i) => (
          <span
            key={i}
            data-layer="counts"
            className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted-foreground/70 ring-2 ring-surface"
            style={{ left: `${n > 1 ? OWN_FROM + (i / (n - 1)) * (OWN_TO - OWN_FROM) : (OWN_FROM + OWN_TO) / 2}%`, top: `${top(v)}%` }}
          />
        ))}
        <span
          data-layer="counts"
          data-me
          className="absolute size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-counts ring-2 ring-surface"
          style={{ left: `${ME_AT}%`, top: `${top(peer.me)}%` }}
        >
          <span
            className={cn(
              "absolute left-1/2 -translate-x-1/2 text-[10px] leading-3 font-medium whitespace-nowrap text-foreground",
              meAbove ? "bottom-full mb-1.5" : "top-full mt-1.5",
            )}
          >
            {C.me}
          </span>
        </span>
      </div>
      {/* The key as swatches only (D30): each name shows on hover or tap. */}
      <figcaption data-layer="ui">
        <SwatchLegend
          label={copy.reel.timeline.legend.label}
          items={[
            { key: "me", name: C.me, mark: <span aria-hidden className="size-2.5 rounded-full bg-counts" /> },
            { key: "own", name: fmt(C.own, { n }), mark: <span aria-hidden className="size-2 rounded-full bg-muted-foreground/70" /> },
            { key: "median", name: C.median, mark: <span aria-hidden className="w-4 border-t border-dashed border-muted-foreground" /> },
          ]}
        />
      </figcaption>
    </figure>
  );
}

export function CountsBlock({ sc, row, discount }: { sc: string; row: BoardRow | null; discount: string | null }) {
  return (
    <section className={CARD_CLASS}>
      <header data-layer="ui" className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <LayerTag layer="counts" />
          <h2 className="text-ui font-medium">{C.chartTitle}</h2>
          {/* The note and the board's flags in full (the strip above shows them short) wait
              behind one (i) (D30). Counts only: no brain value ever sits in here (D20). */}
          <InfoHint label={C.footnoteLabel}>
            <div className="flex flex-col gap-2">
              <p data-counts-note="">{C.footnote}</p>
              {row?.badges.length ? (
                <div className="flex flex-col gap-1">
                  <p className="text-[11px] text-muted-foreground">{C.flags}</p>
                  <ul data-flags="" className="flex flex-wrap gap-1.5">
                    {row.badges.map((b) => (
                      <li key={b.key}>
                        <LayerValue layer="counts" className="inline-flex h-5 items-center rounded-sm border border-line px-1.5 text-[11px]">
                          {b.label}
                        </LayerValue>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          </InfoHint>
        </div>
        <DiscountForm sc={sc} />
      </header>
      <div className="flex flex-col gap-3 p-4">
        {row?.peer ? (
          <CountsChart peer={row.peer} />
        ) : (
          <p data-layer="ui" className="text-ui text-muted-foreground">
            {C.noPeer}
          </p>
        )}
        {discount ? (
          <p data-row className="flex flex-wrap items-baseline gap-x-2 text-ui">
            <span data-layer="ui" className="text-[11px] text-muted-foreground">
              {copy.reel.discount.current}
            </span>
            <LayerValue layer="counts">{discount}</LayerValue>
          </p>
        ) : null}
      </div>
    </section>
  );
}
