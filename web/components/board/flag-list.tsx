// A reel's flags (thin baseline, discounted, under 2x...): counts caveats, drawn solid and sans
// like every counts value. In a table cell only the first shows, with "+N" and the full list
// in the title; the cards show them all; the peek shows them all in full. With `short` (table and
// cards, D30 less text) each flag shows its head only ("under 2x"), and the full labels stay in
// the hover text and the peek.

import { flagHead, type Reel } from "@/components/board/model";
import { LayerValue } from "@/components/shared/layer-value";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

const PILL = "inline-flex h-5 max-w-full items-center rounded-sm border border-line px-1.5 text-[12px] leading-4 text-foreground/80";

export function FlagList({ reel, max, short, className }: { reel: Reel; max?: number; short?: boolean; className?: string }) {
  const badges = reel.badges;
  if (!badges.length) {
    return (
      <LayerValue layer="counts" className={cn("text-muted-foreground", className)}>
        {copy.board.noFlags}
      </LayerValue>
    );
  }
  const shown = max === undefined ? badges : badges.slice(0, max);
  const rest = badges.length - shown.length;
  return (
    <span className={cn("flex min-w-0 items-center gap-1", max === undefined && "flex-wrap", className)} title={reel.cells.flags}>
      {shown.map((b) => (
        <LayerValue key={b.key} layer="counts" data-flag={b.key} className={cn(PILL, max !== undefined && "min-w-0")}>
          <span className="truncate">{short ? flagHead(b.label) : b.label}</span>
        </LayerValue>
      ))}
      {rest > 0 ? (
        <LayerValue layer="counts" className="shrink-0 text-[12px] leading-4 text-muted-foreground">
          {fmt(copy.board.moreFlags, { n: rest })}
        </LayerValue>
      ) : null}
    </span>
  );
}
