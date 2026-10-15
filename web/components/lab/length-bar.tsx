// The draft's length as one thin bar: each beat a segment over its estimated seconds, and a tick
// at the target. A fact about the draft (data-layer facts), so it wears the facts colour, ink, in
// two alternating steps with a 2px surface gap between beats (never a status colour: going past
// the target is told by the check's dot and word, not by red). The segments grow in from the left
// once on first render (none under reduced motion); the target tick carries a 2px surface ring so
// it reads where it crosses a segment.

import { copy, fmt } from "@/lib/copy";
import type { LabPage } from "@/lib/hosted";
import { cn } from "@/lib/utils";

type LengthBarProps = Pick<LabPage, "beats" | "est_s" | "target_s"> & { className?: string };

export function LengthBar({ beats, est_s, target_s, className }: LengthBarProps) {
  const top = Math.max(est_s || 0, target_s || 0, 1) * 1.08;
  const pct = (s: number) => `${Math.max(0, Math.min(100, (s / top) * 100)).toFixed(2)}%`;
  const label = target_s
    ? fmt(copy.lab.length.bar, { est: Math.round(est_s), target: Math.round(target_s) })
    : fmt(copy.lab.length.barNoTarget, { est: Math.round(est_s) });
  return (
    <div data-layer="facts" data-length-bar role="img" aria-label={label} className={cn("relative h-5", className)}>
      <div className="absolute inset-x-0 top-1.5 h-2 overflow-hidden rounded-full bg-subtle">
        <div className="grow-x absolute inset-0">
          {beats.map((b, i) =>
            b.end > b.start ? (
              <span
                key={i}
                data-layer="facts"
                data-length-beat={i}
                title={b.chip ?? undefined}
                className={cn("absolute inset-y-0 border-r-2 border-surface", i % 2 ? "bg-facts/45" : "bg-facts/85")}
                style={{ left: pct(b.start), width: pct(b.end - b.start) }}
              />
            ) : null,
          )}
        </div>
      </div>
      {target_s ? (
        <span
          data-layer="facts"
          data-length-target
          aria-hidden
          className="absolute top-0 h-5 w-0.5 -translate-x-1/2 rounded-full bg-facts ring-2 ring-surface"
          style={{ left: pct(target_s) }}
        />
      ) : null}
    </div>
  );
}
