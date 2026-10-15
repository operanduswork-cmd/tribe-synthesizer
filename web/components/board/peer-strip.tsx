"use client";

// Where this reel's plays sit among the creator's own reels: short muted ticks for the baseline
// reels, a tall ink tick for the own median, and this reel as a counts-teal dot with a 2px surface
// ring, on the log scale the strategist computed (positions 0..1). Counts only, drawn solid. One
// strip per reel, never a trend line. Teal is the counts layer's mark colour, never "good"; the
// legend stays ink. Counts never animate.
//
// D30 (less text): the legend ("dot: this reel · tall tick: own median · ...") is not a line
// under the strip any more. It is the strip's accessible name and sits behind the (i) at its end,
// one tap away, in the counts layer.

import type { Reel } from "@/components/board/model";
import { InfoHint } from "@/components/shared/info-hint";
import { copy } from "@/lib/copy";

const H = 20;

/** 0..1 to a percentage, kept 2% inside each edge so the dot is never clipped. */
const pct = (v: number) => `${(2 + Math.min(1, Math.max(0, v)) * 96).toFixed(2)}%`;

export function PeerStrip({ peer }: { peer: NonNullable<Reel["peer"]> }) {
  return (
    <div data-line="peer" className="flex items-center gap-2">
      <svg data-layer="counts" height={H} className="block min-w-0 flex-1 overflow-visible text-foreground" role="img" aria-label={peer.label}>
        <line x1="2%" x2="98%" y1={H / 2} y2={H / 2} className="counts-line stroke-line" strokeWidth={2} strokeLinecap="round" />
        {peer.ticks.map((t, i) => (
          <line
            key={i}
            data-peer="tick"
            x1={pct(t)}
            x2={pct(t)}
            y1={H / 2 - 4}
            y2={H / 2 + 4}
            className="stroke-muted-foreground"
            strokeOpacity={0.55}
            strokeWidth={1.5}
            strokeLinecap="round"
          />
        ))}
        <line data-peer="median" x1={pct(peer.median)} x2={pct(peer.median)} y1={1} y2={H - 1} stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
        <circle data-peer="me" cx={pct(peer.me)} cy={H / 2} r={5} className="fill-counts stroke-surface" strokeWidth={2} />
      </svg>
      <InfoHint layer="counts" label={copy.board.peek.stripHint} side="top" align="end" contentClassName="tabular-nums">
        {peer.label}
      </InfoHint>
    </div>
  );
}
