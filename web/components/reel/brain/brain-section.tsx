"use client";

// The 3D brain in the timeline card (D28): a figure of its own (data-chart="brain"), between the
// card header and the lanes, a sibling of the timeline slider, never inside it. It follows the
// page's one selected second (ReelTime): the lanes, this map, its scrubber and the Areas tab move
// together, and Play steps all of them.
//
// Loading: a fixed-ratio skeleton (2:1 on a laptop, 8:5 on a phone) until the figure comes
// within 200px of the screen; then a WebGL2 check on a throwaway canvas (so three.js never logs an
// error where it cannot draw), then the data (mesh, atlas, frames; a thin progress bar) and the
// three.js chunk in parallel. Without WebGL, or when the context is lost, the fallback shows: the
// peak picture on a white tile when the site holds one, else a short note, with a reload button
// after a loss.
//
// Controls (Vimeo editor / ElevenLabs reference: play and "0:12 / 0:41" by the track; Copilot 3D:
// a small floating two-button angle toggle): Play/Pause, the time, a native range scrubber
// (warm ticks at HIGH seconds, 44px tall on touch), the angle presets, Reset and the downloads.
// The legend is compact: the map's own colours from lower to higher and the "near 0" grey swatch;
// "one colour scale for this whole reel" and the longer note sit behind one (i) (D30).

import { PauseIcon, PlayIcon, RotateCcwIcon } from "lucide-react";
import dynamic from "next/dynamic";
import Image from "next/image";
import { useEffect, useRef, useState, useSyncExternalStore, type PointerEvent } from "react";

import { DownloadMenu } from "@/components/reel/download-menu";
import { SwatchLegend } from "@/components/reel/hint-popover";
import { useReelTime } from "@/components/reel/reel-time";
import { clock } from "@/components/reel/time";
import { InfoHint } from "@/components/shared/info-hint";
import { Button } from "@/components/ui/button";
import { copy, fmt } from "@/lib/copy";
import { useReducedMotion } from "@/lib/use-reduced-motion";
import { cn } from "@/lib/utils";

import type { BrainData } from "./assets";
import type { Angle, BrainCanvasHandle } from "./brain-canvas";
import { BrainTooltip } from "./brain-tooltip";
import { legendGradient } from "./lut";
import { useBrainPalette } from "./use-brain-palette";
import type { BrainView } from "./view";

const BrainCanvas = dynamic(() => import("./brain-canvas").then((m) => m.BrainCanvas), { ssr: false });

const B = copy.reel.brain;

export const BRAIN_ID = "reel-brain";

/** WebGL2 on a throwaway canvas, released at once. */
function hasWebgl2(): boolean {
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    if (!gl) return false;
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return true;
  } catch {
    return false;
  }
}

const COARSE = "(pointer: coarse)";
function subscribeCoarse(fn: () => void) {
  const mq = window.matchMedia?.(COARSE);
  mq?.addEventListener("change", fn);
  return () => mq?.removeEventListener("change", fn);
}
const isCoarse = () => window.matchMedia?.(COARSE).matches ?? false;

export type PeakTile = { src: string; alt: string; caption: string };

type BrainSectionProps = {
  view: BrainView;
  /** The time axis end as the axis shows it ("0:42"). */
  endLabel: string;
  /** The peak picture for the fallback (db mode with a stored picture), else null. */
  peak: PeakTile | null;
};

export function BrainSection({ view, endLabel, peak }: BrainSectionProps) {
  const { t, lastSec, playing, source, seek, toggle } = useReelTime();
  const reduced = useReducedMotion();
  const palette = useBrainPalette();
  const touch = useSyncExternalStore(subscribeCoarse, isCoarse, () => false);

  const boxRef = useRef<HTMLDivElement>(null);
  const handle = useRef<BrainCanvasHandle>(null);
  const [support, setSupport] = useState<"unknown" | "webgl" | "none">("unknown");
  const [data, setData] = useState<BrainData | null>(null);
  const [progress, setProgress] = useState(0);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  const [lost, setLost] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [angle, setAngle] = useState<Angle>("outside");
  const [box, setBox] = useState<{ w: number; h: number } | undefined>(undefined);

  // Start once the figure comes near the screen.
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        io.disconnect();
        setSupport(hasWebgl2() ? "webgl" : "none");
      },
      { rootMargin: "200px" },
    );
    io.observe(el);
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => {
      io.disconnect();
      ro.disconnect();
    };
  }, []);

  // The data, fetched alongside the three.js chunk.
  useEffect(() => {
    if (support !== "webgl") return;
    let live = true;
    import("./assets")
      .then((m) => m.loadBrain(view, (share) => live && setProgress(share)))
      // Keep the same object when the cached assets come back (a reload): a new object would
      // rebuild the scene on a canvas whose context was just released.
      .then((d) => live && setData((prev) => (prev && prev.mesh === d.mesh && prev.atlas === d.atlas && prev.frames === d.frames ? prev : d)))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [support, view, attempt]);

  const shown = t ?? 0;
  const fallback = support === "none" ? "none" : lost || failed ? "lost" : null;
  const drawing = support === "webgl" && data !== null && !lost && !failed;

  function reload() {
    setLost(false);
    setFailed(false);
    setReady(false);
    setAttempt((a) => a + 1);
  }

  return (
    <figure id={BRAIN_ID} data-chart="brain" aria-label={B.title} className="flex scroll-mt-20 flex-col gap-2.5 border-b border-line px-4 pt-3 pb-3">
      <div ref={boxRef} className="relative aspect-[8/5] w-full overflow-hidden rounded-lg bg-subtle/60 sm:aspect-[2/1]">
        {!ready && !fallback ? <Skeleton progress={support === "webgl" ? progress : null} /> : null}
        {drawing ? (
          <BrainCanvas
            key={attempt}
            view={view}
            data={data}
            t={shown}
            playing={source === "play"}
            reduced={reduced}
            touch={touch}
            palette={palette}
            label={fmt(B.canvasLabel, { time: clock(shown) })}
            onReady={() => setReady(true)}
            onLost={() => setLost(true)}
            onAngle={setAngle}
            handle={handle}
          />
        ) : null}
        {fallback ? <Fallback reason={fallback} peak={peak} onReload={reload} /> : null}
        {ready && drawing ? (
          <>
            <div
              role="group"
              aria-label={B.angleLabel}
              data-layer="ui"
              className="absolute top-2 right-2 flex items-center gap-0.5 rounded-lg border border-line bg-surface/90 p-0.5 backdrop-blur-sm"
            >
              {(["outside", "inside"] as const).map((a) => (
                <button
                  key={a}
                  type="button"
                  aria-pressed={angle === a}
                  data-angle-button={a}
                  onClick={() => handle.current?.setAngle(a)}
                  className="inline-flex h-7 items-center rounded-md px-2.5 text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground aria-pressed:bg-subtle aria-pressed:text-foreground pointer-coarse:h-11 pointer-coarse:px-3"
                >
                  {a === "outside" ? B.angleOutside : B.angleInside}
                </button>
              ))}
              <button
                type="button"
                aria-label={B.reset}
                data-brain-reset=""
                onClick={() => handle.current?.reset()}
                className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground pointer-coarse:size-11"
              >
                <RotateCcwIcon aria-hidden className="size-3.5" />
              </button>
            </div>
            <span aria-hidden data-layer="ui" className="pointer-events-none absolute bottom-1.5 left-1/4 -translate-x-1/2 text-[11px] text-muted-foreground">
              {B.hemi.left}
            </span>
            <span aria-hidden data-layer="ui" className="pointer-events-none absolute right-1/4 bottom-1.5 translate-x-1/2 text-[11px] text-muted-foreground">
              {B.hemi.right}
            </span>
            <BrainTooltip view={view} t={t} mode="float" box={box} />
          </>
        ) : null}
      </div>

      <BrainTooltip view={view} t={t} mode="card" />

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <Button
          variant="outline"
          size="icon-sm"
          data-brain-play=""
          aria-label={playing ? B.pause : B.play}
          onClick={toggle}
          className="rounded-full"
        >
          {playing ? <PauseIcon aria-hidden /> : <PlayIcon aria-hidden className="translate-x-px" />}
        </Button>
        <span data-layer="ui" className="flex items-baseline gap-1 font-mono text-mono tabular-nums">
          <span className="sr-only">{fmt(B.timeOf, { time: clock(shown), end: endLabel })}</span>
          <span key={shown} aria-hidden className="text-foreground readout-in">
            {clock(shown)}
          </span>
          <span aria-hidden className="text-muted-foreground">
            {B.timeSep}
          </span>
          <span aria-hidden className="text-muted-foreground">
            {endLabel}
          </span>
        </span>
        <Scrubber
          view={view}
          t={t}
          lastSec={lastSec}
          source={source}
          onSeek={seek}
          className="order-last basis-full sm:order-none sm:min-w-32 sm:flex-1 sm:basis-auto"
        />
        <DownloadMenu view={view} className="ml-auto sm:ml-0" />
      </div>

      <Legend gradient={legendGradient(palette, view.greyBelow, view.fullAt)} />
    </figure>
  );
}

function Skeleton({ progress }: { progress: number | null }) {
  return (
    <div data-brain-skeleton="" aria-hidden className="absolute inset-0">
      <div className="absolute inset-0 flex items-center justify-center gap-[6%] px-[6%]">
        <span className="aspect-[3/2] w-[42%] animate-pulse rounded-[45%] bg-line/70" />
        <span className="aspect-[3/2] w-[42%] animate-pulse rounded-[45%] bg-line/70" />
      </div>
      {progress !== null ? (
        <div className="absolute inset-x-0 bottom-0 h-0.5 bg-line/60">
          <div className="h-full origin-left bg-indigo-accent transition-transform duration-200" style={{ transform: `scaleX(${progress})` }} />
        </div>
      ) : null}
      <span className="sr-only">{B.loading}</span>
    </div>
  );
}

function Fallback({ reason, peak, onReload }: { reason: "none" | "lost"; peak: PeakTile | null; onReload: () => void }) {
  return (
    <div data-brain-fallback={reason} className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-3 text-center">
      {peak ? (
        <figure className="flex min-h-0 flex-col items-center gap-1">
          <Image
            data-layer="brain"
            src={peak.src}
            alt={peak.alt}
            width={480}
            height={240}
            unoptimized
            className="h-auto max-h-full min-h-0 w-auto max-w-full rounded-md bg-white p-1"
          />
          <figcaption data-layer="ui" className="text-[11px] leading-4 text-muted-foreground">
            {peak.caption}
          </figcaption>
        </figure>
      ) : null}
      <p data-layer="ui" className="max-w-72 text-ui text-muted-foreground">
        {reason === "none" ? B.noWebgl : B.lost}
      </p>
      {reason === "lost" ? (
        <Button size="sm" variant="outline" onClick={onReload}>
          {B.reload}
        </Button>
      ) : null}
    </div>
  );
}

type ScrubberProps = {
  view: BrainView;
  t: number | null;
  lastSec: number;
  source: string | null;
  onSeek: (t: number, opts: { source: "drag" | "key" }) => void;
  className?: string;
};

/** The brain's own second slider: a native range (keyboard and screen readers for free), drawn
 *  as a track with warm HIGH ticks and a playhead knob that glides like the lanes' playhead. */
function Scrubber({ view, t, lastSec, source, onSeek, className }: ScrubberProps) {
  const dragging = useRef(false);
  const at = (s: number) => `calc(8px + (100% - 16px) * ${lastSec > 0 ? Math.min(1, Math.max(0, s / lastSec)) : 0})`;
  const value = t ?? 0;
  return (
    <div
      data-brain-scrubber=""
      className={cn(
        "relative h-7 rounded-md has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-indigo-accent pointer-coarse:h-11",
        className,
      )}
    >
      <div aria-hidden className="absolute inset-x-2 top-1/2 h-1 -translate-y-1/2 rounded-full bg-line">
        <div className="glide h-full rounded-full bg-foreground/30" data-glide={source ?? "key"} style={{ width: `${lastSec > 0 ? (value / lastSec) * 100 : 0}%` }} />
      </div>
      {view.highs.map((h) => (
        <span
          key={h.t}
          aria-hidden
          data-layer="brain"
          data-encoding="plain"
          data-high={h.t}
          className={cn("absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brain-warm", h.edge && "opacity-50")}
          style={{ left: at(h.t) }}
        />
      ))}
      <span
        aria-hidden
        data-brain-playhead={value}
        data-glide={source ?? "key"}
        className="glide pointer-events-none absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-accent ring-2 ring-[var(--playhead-halo)]"
        style={{ left: at(value) }}
      />
      <input
        type="range"
        min={0}
        max={lastSec}
        step={1}
        value={value}
        aria-label={B.second}
        aria-valuenow={value}
        aria-valuetext={clock(value)}
        onPointerDown={(e: PointerEvent<HTMLInputElement>) => {
          dragging.current = e.button === 0;
        }}
        onPointerUp={() => {
          dragging.current = false;
        }}
        onPointerCancel={() => {
          dragging.current = false;
        }}
        onChange={(e) => onSeek(Number(e.currentTarget.value), { source: dragging.current ? "drag" : "key" })}
        className="absolute inset-0 m-0 size-full cursor-pointer touch-pan-y appearance-none opacity-0 [&::-moz-range-thumb]:size-4 [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none"
      />
    </div>
  );
}

/** The colour key, short (D30): "lower [gradient] higher", the "near 0" grey as a swatch whose
 *  name shows on hover or tap, and one (i) that opens to "one colour scale for this whole reel"
 *  (D28) and how the points are coloured. */
function Legend({ gradient }: { gradient: string }) {
  const L = B.legend;
  return (
    <div data-brain-key="" className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-4 text-muted-foreground">
      <span data-layer="ui" className="inline-flex items-center gap-1.5">
        {L.lower}
        <span
          aria-hidden
          title={L.scale}
          data-layer="brain"
          data-encoding="plain"
          data-brain-legend=""
          className="relative h-2 w-24 rounded-full"
          style={{ background: gradient }}
        >
          <span className="absolute inset-y-[-2px] left-1/2 w-px -translate-x-1/2 bg-foreground/40" />
        </span>
        {L.higher}
      </span>
      <SwatchLegend label={L.label} items={[{ key: "near", name: L.near, mark: <span aria-hidden className="size-2 rounded-sm bg-brain-near" /> }]} />
      <InfoHint label={fmt(copy.ui.hintAbout, { topic: L.label })} layer="brain" side="top" align="end">
        <span data-brain-key-hint="" className="flex flex-col gap-1.5">
          <span>{L.scale}</span>
          <span>{L.about}</span>
        </span>
      </InfoHint>
    </div>
  );
}

/** The atlas and HCP credits (LICENSES/CREDITS.md section 4), word for word behind one small
 *  "Credits" (i) under the brain view's card and in the Areas tab (D30). The numbers file keeps
 *  them in full. */
export function BrainCredits({ className }: { className?: string }) {
  return (
    <div data-brain-credits="" data-layer="ui" className={cn("flex items-center gap-1.5 text-[11px] leading-4 text-muted-foreground", className)}>
      <span>{B.creditsLabel}</span>
      <InfoHint label={B.creditsLabel} align="start">
        <span data-credits-text="" className="flex flex-col gap-2 text-[11px] leading-4">
          <span>{B.credit.atlas}</span>
          <span>{B.credit.hcp}</span>
        </span>
      </InfoHint>
    </div>
  );
}
