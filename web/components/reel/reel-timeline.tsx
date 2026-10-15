"use client";

// The reel's timeline (Grain reference: one track per lane on one time axis; YouTube Studio:
// a vertical playhead; Pinterest: predicted lines dotted). Ported from the lanes drawing in
// dashboard/template.html: display_z lines on one shared scale, HIGH marks at peaks, FLAT bars,
// the time axis. No word strip: words stay on the laptop. Counts never appear here (D20).
//
// Every x position is a percentage of the time axis, so the server render is already exact and
// nothing is measured. The lane lines are SVG stretched to the lane (preserveAspectRatio none)
// with non-scaling strokes, so the dots stay round at any width.
//
// Round 2 (colour + motion, fewer words): each lane fills warm above this reel's average and cool
// below (two clip paths, soft fills, the dotted line kept on top); HIGH marks are warm and FLAT
// bars cool (the brain's diverging pair, never a status); each lane header leads with the line's
// icon and ends in a tinted chip with its band at the playhead (a short line per lane stays for
// screen readers in the readout); the drift is a small arrow with a tooltip. Round 3 (D30): the
// line's own label shows on hover of its name, and nothing asks to "pick a second". Hovering a lane's
// name outlines that line's areas on the 3D brain. The playhead glides by what moved it: 1000 ms
// linear while playing, 120 ms on keys and chips, at once while dragging (globals.css .glide),
// with a 2px surface halo and a time chip on the axis (ElevenLabs reference).

import { InfoIcon, MoveRightIcon, TrendingDownIcon, TrendingUpIcon } from "lucide-react";
import { useId, useRef, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import { LayerValue } from "@/components/shared/layer-value";
import { TimeChip } from "@/components/shared/time-chip";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

import { clearFocus, setFocus } from "./brain/brain-focus";
import { LineIcon } from "./brain/line-icon";
import { useReelTime } from "./reel-time";
import { LINE_KEYS, band, clock, clockRange, laneYMax, pct, type Band, type LineKey } from "./time";

export type TimelineBeat = { start: number; end: number; kind: string; name: string; suggested: boolean };

export type TimelineBrain = {
  timeS: number[];
  lines: Record<LineKey, { label: string; displayZ: Array<number | null>; trend: "rising" | "falling" | "flat" | null }>;
  peaks: Array<{ t: number; edge: boolean }>;
  flats: Array<{ start: number; end: number; edge: boolean }>;
};

type ReelTimelineProps = {
  /** The end of the drawn axis in seconds (covers the last row). */
  tEnd: number;
  beats: TimelineBeat[];
  brain: TimelineBrain | null;
  /** Shown over empty lanes when there is no brain read to draw (Nextdoor reference). A phone
   *  shows it as one row under the Beats lane instead of four empty lanes. */
  emptyPill?: string;
  /** With no brain read: the note and its action, right under the axis and outside the slider,
   *  so a press on the button never moves the playhead. */
  empty?: ReactNode;
  /** The legend, right under the axis so it stays in view (Pinterest reference). */
  legend?: ReactNode;
};

const T = copy.reel.timeline;
const VB_W = 1000;
const VB_H = 100;
const EDGE_STRIPES = "repeating-linear-gradient(135deg, currentColor 0 2px, transparent 2px 4px)";
const TREND_ICON = { rising: TrendingUpIcon, falling: TrendingDownIcon, flat: MoveRightIcon } as const;

/** The band chip's tint: warm above this reel's average, cool below, plain near it. */
const BAND_TINT: Record<Band, string> = {
  wellAbove: "bg-brain-warm-soft text-foreground",
  above: "bg-brain-warm-soft text-foreground",
  near: "bg-subtle text-muted-foreground",
  below: "bg-brain-cool-soft text-foreground",
  wellBelow: "bg-brain-cool-soft text-foreground",
  none: "bg-subtle text-muted-foreground",
};

export function ReelTimeline({ tEnd, beats, brain, emptyPill, empty, legend }: ReelTimelineProps) {
  const { t, lastSec, seek, source } = useReelTime();
  const tracks = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const clipBase = useId().replace(/[^A-Za-z0-9_-]/g, "");

  function secondAt(clientX: number): number {
    const box = tracks.current?.getBoundingClientRect();
    if (!box || box.width <= 0) return t ?? 0;
    return Math.floor(((clientX - box.left) / box.width) * tEnd);
  }
  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return;
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    seek(secondAt(e.clientX), { source: "drag" });
  }
  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    if (dragging.current) seek(secondAt(e.clientX), { source: "drag" });
  }
  function onPointerUp(e: PointerEvent<HTMLDivElement>) {
    dragging.current = false;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  }
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const step: Record<string, number> = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -5, PageUp: 5 };
    if (e.key in step) seek(t === null ? (step[e.key] > 0 ? 0 : lastSec) : t + step[e.key]);
    else if (e.key === "Home") seek(0);
    else if (e.key === "End") seek(lastSec);
    else return;
    e.preventDefault();
  }

  const yMax = brain ? laneYMax(LINE_KEYS.map((k) => brain.lines[k].displayZ)) : 1;
  const xv = (s: number) => (s / tEnd) * VB_W;
  // Chips that share a boundary second (0:00-0:03, then 0:03-0:07) would overlap by one second,
  // so each drawn beat ends where the next one starts; the Beats tab keeps the raw chips.
  const drawn = [...beats]
    .sort((a, b) => a.start - b.start)
    .map((b, i, all) => ({ ...b, end: Math.max(b.start + 1, Math.min(b.end, all[i + 1]?.start ?? b.end)) }));
  const beatAt = t === null ? undefined : drawn.find((b) => t >= b.start && t < b.end);
  const peakAt = t === null ? undefined : brain?.peaks.find((p) => p.t === t);
  const flatAt = t === null ? undefined : brain?.flats.find((f) => t >= f.start && t < f.end);
  const rowAtT = brain && t !== null ? brain.timeS.findIndex((s) => Math.floor(s) === t) : -1;
  const glide = source ?? "key";

  return (
    <div className="flex flex-col gap-3">
      <div
        role="slider"
        tabIndex={0}
        aria-label={brain ? T.label : T.labelNoBrain}
        aria-valuemin={0}
        aria-valuemax={lastSec}
        aria-valuenow={t ?? 0}
        aria-valuetext={t === null ? T.none : clock(t)}
        data-chart="timeline"
        className="cursor-crosshair touch-pan-y rounded-md outline-none select-none focus-visible:ring-2 focus-visible:ring-indigo-accent focus-visible:ring-offset-4 focus-visible:ring-offset-surface"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
      >
        <div ref={tracks} className="relative flex flex-col gap-2.5 lg:gap-2">
          <Track label={T.beats}>
            <div className="relative h-6">
              {drawn.map((b, i) => (
                <span
                  key={i}
                  data-layer="shape"
                  data-status={b.suggested ? "suggested" : "accepted"}
                  title={fmt(T.beatAt, { kind: b.kind, name: b.name })}
                  className={cn(
                    "absolute inset-y-0 flex items-center overflow-hidden rounded-sm border px-1.5 font-mono text-mono leading-none whitespace-nowrap",
                    b.suggested ? "border-indigo-accent text-indigo-accent" : "border-line bg-subtle text-foreground",
                  )}
                  style={{ left: `calc(${pct(b.start, tEnd)}% + 1px)`, width: `calc(${pct(b.end - b.start, tEnd)}% - 2px)` }}
                >
                  {/* A narrow beat shows only its outline (the title and the readout name it); a
                      wider one ends in an ellipsis, never half a word. */}
                  <span className={cn("min-w-0 truncate", pct(b.end - b.start, tEnd) < 8 && "sr-only")}>{b.kind}</span>
                </span>
              ))}
            </div>
          </Track>

          {brain ? (
            <>
              <Track label={T.moments}>
                <div className="relative h-3">
                  {brain.flats.map((f, i) => (
                    <span
                      key={`f${i}`}
                      data-layer="brain"
                      data-encoding="plain"
                      title={fmt(T.inFlat, { time: clockRange(f.start, f.end, lastSec) })}
                      className={cn("absolute top-1 h-1.5 rounded-sm", f.edge ? "text-brain-cool/70" : "bg-brain-cool/80")}
                      style={{
                        left: `${pct(f.start, tEnd)}%`,
                        width: `${Math.max(0.6, pct(f.end - f.start, tEnd))}%`,
                        background: f.edge ? EDGE_STRIPES : undefined,
                      }}
                    />
                  ))}
                  {brain.peaks.map((p, i) => (
                    <span
                      key={`p${i}`}
                      data-layer="brain"
                      data-encoding="plain"
                      title={`${T.inHigh} ${clock(p.t)}`}
                      className={cn("absolute top-0 -translate-x-1/2", p.edge && "opacity-50")}
                      style={{ left: `${pct(p.t + 0.5, tEnd)}%` }}
                    >
                      <svg width="10" height="9" viewBox="0 0 10 9" aria-hidden className="block fill-brain-warm">
                        <path d="M0 0H10L5 9Z" />
                      </svg>
                    </span>
                  ))}
                </div>
              </Track>
              {LINE_KEYS.map((k, laneIndex) => {
                const L = brain.lines[k];
                const y = (z: number) => VB_H / 2 - (z / yMax) * (VB_H / 2 - 4);
                let d = "";
                let area = "";
                let run: string[] = [];
                const close = () => {
                  if (run.length) area += `M${run[0].split(" ")[0]} ${VB_H / 2}L${run.join("L")}L${run[run.length - 1].split(" ")[0]} ${VB_H / 2}Z`;
                  run = [];
                };
                let pen = false;
                L.displayZ.forEach((z, r) => {
                  if (typeof z !== "number" || !Number.isFinite(z)) {
                    pen = false;
                    close();
                    return;
                  }
                  const pt = `${xv((brain.timeS[r] ?? r) + 0.5).toFixed(1)} ${y(z).toFixed(1)}`;
                  d += `${pen ? "L" : "M"}${pt}`;
                  run.push(pt);
                  pen = true;
                });
                close();
                const b = rowAtT >= 0 ? band(L.displayZ[rowAtT]) : null;
                const Trend = L.trend ? TREND_ICON[L.trend] : null;
                const clip = `${clipBase}-${k}`;
                return (
                  <div key={k}>
                    <div className="flex h-4 items-center justify-between gap-2 text-[11px] leading-4">
                      {/* The line's own label ("predicted visual response") names it on hover (D30). */}
                      <span
                        data-lane-label={k}
                        title={L.label}
                        className="flex min-w-0 items-center gap-1.5"
                        onPointerEnter={() => setFocus({ kind: "line", line: k, from: "lane", pinned: false })}
                        onPointerLeave={() => clearFocus(`line-${k}`)}
                      >
                        <LineIcon line={k} className="size-3 text-muted-foreground" />
                        <span data-layer="ui" className="shrink-0 font-medium">
                          {T.lanes[k]}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-1.5">
                        {Trend ? (
                          <span
                            role="img"
                            data-layer="brain"
                            data-encoding="plain"
                            data-drift={L.trend}
                            aria-label={fmt(T.drift, { trend: L.trend! })}
                            title={fmt(T.drift, { trend: L.trend! })}
                            className="text-muted-foreground"
                          >
                            <Trend aria-hidden className="size-3.5" />
                          </span>
                        ) : null}
                        {b ? (
                          <span
                            key={`${k}-${b}`}
                            data-layer="brain"
                            data-encoding="plain"
                            data-band={b}
                            title={T.bands[b]}
                            className={cn("readout-in rounded-sm px-1.5 font-mono text-[10px] leading-4 whitespace-nowrap", BAND_TINT[b])}
                          >
                            {T.bandShort[b]}
                          </span>
                        ) : null}
                      </span>
                    </div>
                    <svg
                      data-layer="brain"
                      viewBox={`0 0 ${VB_W} ${VB_H}`}
                      preserveAspectRatio="none"
                      aria-hidden
                      className="lane-reveal mt-1 block h-10 w-full rounded-md bg-subtle md:h-12 lg:h-9 2xl:h-12"
                      style={{ "--lane-index": laneIndex } as CSSProperties}
                    >
                      <defs>
                        <clipPath id={`${clip}-up`}>
                          <rect x={0} y={0} width={VB_W} height={VB_H / 2} />
                        </clipPath>
                        <clipPath id={`${clip}-down`}>
                          <rect x={0} y={VB_H / 2} width={VB_W} height={VB_H / 2} />
                        </clipPath>
                      </defs>
                      {brain.flats.map((f, i) => (
                        <rect
                          key={`f${i}`}
                          x={xv(f.start)}
                          y={0}
                          width={Math.max(2, xv(f.end) - xv(f.start))}
                          height={VB_H}
                          className={f.edge ? "fill-brain-cool/[0.05]" : "fill-brain-cool/[0.10]"}
                        />
                      ))}
                      {area ? (
                        <>
                          <path d={area} clipPath={`url(#${clip}-up)`} className="fill-brain-warm-soft" />
                          <path d={area} clipPath={`url(#${clip}-down)`} className="fill-brain-cool-soft" />
                        </>
                      ) : null}
                      <line x1={0} x2={VB_W} y1={VB_H / 2} y2={VB_H / 2} vectorEffect="non-scaling-stroke" className="stroke-line" strokeWidth={1} />
                      {brain.peaks.map((p, i) => (
                        <line
                          key={`p${i}`}
                          x1={xv(p.t + 0.5)}
                          x2={xv(p.t + 0.5)}
                          y1={0}
                          y2={VB_H}
                          vectorEffect="non-scaling-stroke"
                          className="stroke-brain-warm/50"
                          strokeWidth={1}
                        />
                      ))}
                      {d ? (
                        <path d={d} vectorEffect="non-scaling-stroke" strokeWidth={2} strokeLinejoin="round" className="brain-line fill-none stroke-foreground" />
                      ) : null}
                    </svg>
                  </div>
                );
              })}
            </>
          ) : (
            <div className="relative flex flex-col gap-2.5">
              {/* A laptop previews the four lanes, dashed, under a floating pill; a phone shows
                  the pill as one row under the Beats lane instead. */}
              {LINE_KEYS.map((k) => (
                <div key={k} aria-hidden className="max-md:hidden">
                  <div data-layer="ui" className="h-4 text-[11px] leading-4 text-muted-foreground">
                    {T.lanes[k]}
                  </div>
                  <div className="mt-1 h-8 rounded-md border border-dashed border-line" />
                </div>
              ))}
              {emptyPill ? (
                <div className="md:absolute md:inset-0 md:flex md:items-center md:justify-center">
                  <span
                    data-layer="ui"
                    className="flex h-10 w-full items-center gap-2 rounded-md bg-subtle px-3 text-ui text-muted-foreground md:h-auto md:w-auto md:rounded-full md:border md:border-line md:bg-surface md:px-3 md:py-1 md:text-foreground"
                  >
                    <InfoIcon aria-hidden className="size-4 shrink-0 md:hidden" />
                    {emptyPill}
                  </span>
                </div>
              ) : null}
            </div>
          )}

          {t !== null ? (
            <span
              aria-hidden
              data-playhead={t}
              data-glide={glide}
              className="glide pointer-events-none absolute inset-y-0 w-px -translate-x-1/2 bg-indigo-accent shadow-[0_0_0_2px_var(--playhead-halo)]"
              style={{ left: `${pct(t + 0.5, tEnd)}%` }}
            >
              <span className="absolute -top-1 left-1/2 size-2 -translate-x-1/2 rounded-full bg-indigo-accent" />
            </span>
          ) : null}
        </div>
        <Axis tEnd={tEnd} lastSec={lastSec} t={t} glide={glide} />
      </div>
      {!brain && empty ? empty : null}
      {legend}

      <div aria-live="polite" className="flex flex-col gap-1.5 border-t border-line pt-3 text-ui empty:border-0 empty:pt-0">
        {t === null ? null : <Readout t={t} lastSec={lastSec} beatAt={beatAt} peakAt={peakAt} flatAt={flatAt} brain={brain} row={rowAtT} />}
      </div>
    </div>
  );
}

type ReadoutProps = {
  t: number;
  lastSec: number;
  beatAt: TimelineBeat | undefined;
  peakAt: TimelineBrain["peaks"][number] | undefined;
  flatAt: TimelineBrain["flats"][number] | undefined;
  brain: TimelineBrain | null;
  row: number;
};

/** What the selected second holds: its beat (shape), then HIGH / FLAT (brain). Each lane's band
 *  shows as a chip in its lane header; the full sentences stay here for screen readers. */
function Readout({ t, lastSec, beatAt, peakAt, flatAt, brain, row }: ReadoutProps) {
  return (
    <>
      <div data-row className="flex min-w-0 items-center gap-2">
        <TimeChip time={clock(t)} layer="shape" active />
        <LayerValue layer="shape" className="truncate">
          {beatAt ? fmt(T.beatAt, { kind: beatAt.kind, name: beatAt.name }) : T.noBeat}
        </LayerValue>
      </div>
      {brain ? (
        <>
          {peakAt || flatAt ? (
            <div data-row className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-mono">
              {peakAt ? (
                <LayerValue layer="brain" encoding="plain" className="inline-flex items-center gap-1.5">
                  <svg width="8" height="7" viewBox="0 0 10 9" aria-hidden className="fill-brain-warm">
                    <path d="M0 0H10L5 9Z" />
                  </svg>
                  {T.inHigh}
                </LayerValue>
              ) : null}
              {flatAt ? (
                <LayerValue layer="brain" encoding="plain" className="inline-flex items-center gap-1.5">
                  <span aria-hidden className="h-1.5 w-3 rounded-sm bg-brain-cool/80" />
                  {fmt(T.inFlat, { time: clockRange(flatAt.start, flatAt.end, lastSec) })}
                </LayerValue>
              ) : null}
              {peakAt?.edge || flatAt?.edge ? (
                <LayerValue layer="brain" encoding="plain" className="text-muted-foreground">
                  {T.edge}
                </LayerValue>
              ) : null}
            </div>
          ) : null}
          <ul className="sr-only">
            {LINE_KEYS.map((k) => (
              <li key={k} data-layer="brain" data-encoding="plain">
                {fmt(T.laneAt, { lane: T.lanes[k], band: T.bandShort[band(row >= 0 ? brain.lines[k].displayZ[row] : null)] })}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

function Track({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div data-layer="ui" className="mb-1 h-4 text-[11px] leading-4 font-medium">
        {label}
      </div>
      {children}
    </div>
  );
}

/** Time ticks: every step on a laptop; start, middle and end on a phone (YouTube Studio). The
 *  last regular tick sits at least one full step before the end label, so the two never touch.
 *  The selected second rides on the axis as a small chip (ElevenLabs reference). */
function Axis({ tEnd, lastSec, t, glide }: { tEnd: number; lastSec: number; t: number | null; glide: string }) {
  const step = tEnd <= 30 ? 5 : tEnd <= 60 ? 10 : tEnd <= 120 ? 20 : tEnd <= 300 ? 60 : 120;
  const ticks: number[] = [];
  for (let s = 0; s <= tEnd - step; s += step) ticks.push(s);
  const end = lastSec + 1;
  const middle = ticks.reduce((best, s) => (Math.abs(s - tEnd / 2) < Math.abs(best - tEnd / 2) ? s : best), 0);
  return (
    <div aria-hidden data-layer="ui" className="relative mt-1.5 h-4 font-mono text-mono text-muted-foreground tabular-nums">
      {ticks.map((s) => (
        <span
          key={s}
          className={cn("absolute top-0", s === 0 ? "" : "-translate-x-1/2", s !== 0 && s !== middle && "hidden md:block")}
          style={{ left: `${pct(s, tEnd)}%` }}
        >
          {clock(s)}
        </span>
      ))}
      <span className="absolute top-0 right-0">{clock(Math.min(end, tEnd))}</span>
      {t !== null ? (
        <span
          data-glide={glide}
          className="glide absolute top-0 z-10 -translate-x-1/2 rounded-sm border border-indigo-accent bg-surface px-1 text-indigo-accent"
          style={{ left: `clamp(1.25rem, ${pct(t + 0.5, tEnd)}%, calc(100% - 1.25rem))` }}
        >
          {clock(t)}
        </span>
      ) : null}
    </div>
  );
}
