// Outliers vs normal as two thin bars on one 0-100% scale (Pinterest audience Compare
// reference), each with its one count on the right (Steep breakdown: right-aligned numbers). The
// group size sits in the bar's hover text and name ("3 of 4 reels"), never as "k/n", which reads
// like a rating when n is 10 (round 4 text cut: one count per bar). No ratio,
// no affinity column: the two shares sit side by side and the reader compares them. A pattern
// with no normal group says "outliers only, no comparison yet" instead of a second bar.
//
// Colour (dataviz emphasis form: one hue plus a grey, checked with its validate_palette.js): the
// outlier bar is the counts layer's teal, the normal bar a neutral grey (muted ink at 55%). Teal
// is the counts layer, never "good", and the grey has no hue, so nothing reads as a red/green
// verdict. Measured pairs: light teal vs grey dE 16-17 normal, 7.6-8.5 colour-blind (the floor
// band, legal because every bar carries its own count and its "k of n" name and keeps its fixed place); dark
// 17.5-18.1 normal, 11.9-12.9 colour-blind. Text stays ink (the outlier label) or muted ink.
//
// Motion: each fill grows in once from the left when it first renders (globals.css .grow-x,
// @starting-style), the normal bar one stagger step after the outlier bar. Only the fill moves;
// the "k of n" values are counts and never animate, and no test measures a fill. Reduced motion
// turns it off (the global block in globals.css).

import { InfoIcon } from "lucide-react";

import { LayerValue } from "@/components/shared/layer-value";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

import type { Pattern } from "./types";

/** The mark colour of each group: bars, legend dots and the key row all use it. */
export const GROUP_FILL = {
  o: "bg-counts",
  m: "bg-muted-foreground/55",
} as const;

/** The legend dot for a group; the bar fill uses the same tone. */
export function GroupDot({ group, className }: { group: "o" | "m"; className?: string }) {
  return <span aria-hidden data-group-dot={group} className={cn("inline-block size-2 shrink-0 rounded-full", GROUP_FILL[group], className)} />;
}

function Bar({ group, k, n }: { group: "o" | "m"; k: number; n: number }) {
  const pct = n > 0 ? Math.max(0, Math.min(100, (k / n) * 100)) : 0;
  const name = group === "o" ? copy.patterns.legend.outliers : copy.patterns.legend.normal;
  return (
    <span
      data-bar={group}
      className="flex h-4 items-center gap-2"
      role="img"
      aria-label={fmt(copy.patterns.bar, { group: name, k, n })}
      title={fmt(copy.patterns.share, { k, n })}
    >
      {/* Square at the zero end, rounded at the value end (dataviz mark spec). */}
      <span className="relative h-2 min-w-0 flex-1 overflow-hidden rounded-r-sm bg-subtle">
        <span
          data-bar-fill={group}
          className={cn(
            "grow-x absolute inset-y-0 left-0 rounded-r-sm",
            GROUP_FILL[group],
            group === "m" && "[transition-delay:var(--motion-stagger)]",
          )}
          style={{ width: `${pct}%` }}
        />
      </span>
      <LayerValue layer="counts" className={cn("w-8 shrink-0 text-right text-ui whitespace-nowrap tabular-nums", group === "m" && "text-muted-foreground")}>
        {k}
      </LayerValue>
    </span>
  );
}

export function CompareBars({ pattern, className }: { pattern: Pick<Pattern, "bars" | "contrast">; className?: string }) {
  const { bars, contrast } = pattern;
  if (!bars) {
    // Spoken-level patterns before enough normal reels are tagged: two words in the row, the
    // data's own contrast line and the no-comparison phrase in the hover text and the open row.
    const hover = contrast.includes(copy.patterns.noCompare) ? contrast : `${contrast} ${copy.patterns.noCompare}`;
    return (
      <span data-compare="outliers-only" title={hover} className={cn("flex min-h-9 items-center gap-1.5 py-1.5", className)}>
        <InfoIcon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
        <LayerValue layer="counts" className="text-ui text-muted-foreground">
          {copy.patterns.outliersOnly}
        </LayerValue>
      </span>
    );
  }
  // No hidden copy of the data's contrast line here: each bar's own label ("Outliers: 3 of 4
  // reels") already says it to a screen reader (round 3 text cut).
  return (
    <span data-compare="two-bars" className={cn("flex flex-col gap-1", className)}>
      <Bar group="o" k={bars.o[0]} n={bars.o[1]} />
      <Bar group="m" k={bars.m[0]} n={bars.m[1]} />
    </span>
  );
}
