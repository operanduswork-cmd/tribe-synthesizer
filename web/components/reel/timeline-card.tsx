// The right column (Grain reference): a sticky card with the reel's 3D brain (D28) on top, then
// the timeline, its key as swatches (Pinterest: dotted means predicted), the moments list with
// time chips at the start of each row (Apollo) and the line icons, and the credits behind an (i).
// Round 3 (D30, less text): one framing chip in the header, its (i) holding the scale, the run
// stamp and the notes on the read. The brain and the timeline are separate charts, side by side in
// the card, never one inside the other; both follow the page's one selected second. Without a
// TRIBE read a laptop shows the lanes empty under a "No TRIBE read yet" pill (Nextdoor) and a
// phone shows a single row; the deep read button and its (i) sit right under the axis. A read
// whose brain page is not on the site keeps the peak picture (live site) in place of the 3D brain.
// Only shape and brain live here; counts have their own chart in the Card tab (D20).

import Image from "next/image";
import type { ReactNode } from "react";

import { InfoHint } from "@/components/shared/info-hint";
import { JobButton } from "@/components/shared/job-button";
import { LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { copy, fmt } from "@/lib/copy";
import { formatUsd } from "@/lib/format";
import type { ReelPage, TribePage } from "@/lib/hosted";
import { JOB_LIMITS, jobKindLabel, jobSpec } from "@/lib/job-kinds";

import { BrainCredits, BrainSection, type PeakTile } from "./brain/brain-section";
import { LineIcon } from "./brain/line-icon";
import type { BrainView } from "./brain/view";
import { SwatchLegend } from "./hint-popover";
import { SeekChip, TIMELINE_ID } from "./reel-time";
import { ReelTimeline, type TimelineBeat, type TimelineBrain } from "./reel-timeline";
import { LINE_KEYS, clock, clockRange } from "./time";

const T = copy.reel.timeline;

/** What the brain side can show: a read, a read that is not on the dashboard, or none. */
export type BrainState = { kind: "read"; tribe: TribePage; image: boolean } | { kind: "missing"; date: string } | { kind: "none" };

type TimelineCardProps = {
  reel: ReelPage;
  brain: BrainState;
  /** The read's brain page for the 3D map, when the site holds one for this reel (D21). */
  view: BrainView | null;
  beats: TimelineBeat[];
  tEnd: number;
  lastSec: number;
};

function toBrain(tribe: TribePage): TimelineBrain {
  const line = (k: (typeof LINE_KEYS)[number]) => ({
    label: tribe.lines[k].label,
    displayZ: tribe.lines[k].display_z,
    trend: tribe.lines[k].trend,
  });
  return {
    timeS: tribe.time_s,
    lines: { seeing: line("seeing"), hearing: line("hearing"), language: line("language"), attention: line("attention") },
    peaks: tribe.peaks.map((p) => ({ t: p.t, edge: p.edge })),
    flats: tribe.flat_stretches.map((f) => ({ start: f.start, end: f.end, edge: f.edge })),
  };
}

function Moments({ tribe, lastSec }: { tribe: TribePage; lastSec: number }) {
  const names = (keys: ReadonlyArray<(typeof LINE_KEYS)[number]>) => keys.map((k) => T.lanes[k]).join(", ");
  const rows = [
    ...tribe.peaks.map((p) => ({ at: p.t, tag: T.inHigh, high: true, chip: clock(p.t), lines: p.driving_lines, edge: p.edge })),
    ...tribe.flat_stretches.map((f) => ({
      at: f.start,
      tag: copy.reel.timeline.legend.flat,
      high: false,
      chip: clockRange(f.start, f.end, lastSec),
      lines: f.driving_lines,
      edge: f.edge,
    })),
  ].sort((a, b) => a.at - b.at);
  return (
    <div className="border-t border-line px-4 py-3">
      <h3 data-layer="ui" className="sr-only">
        {T.momentsTitle}
      </h3>
      {rows.length ? (
        <ol className="flex flex-col">
          {rows.map((r, i) => (
            <li key={i} data-row className="flex min-h-9 flex-wrap items-center gap-x-2.5 gap-y-1 py-1 pointer-coarse:min-h-11">
              <SeekChip time={r.chip} layer="brain" className="min-w-[5.5rem] justify-center" />
              <LayerValue layer="brain" encoding="plain" className="inline-flex w-11 shrink-0 items-center gap-1 font-mono text-mono leading-5">
                <span aria-hidden className={r.high ? "size-1.5 rounded-full bg-brain-warm" : "h-1 w-2 rounded-sm bg-brain-cool"} />
                {r.tag}
              </LayerValue>
              {/* The lines that drive the moment, as the lanes' own icons (D30: no "Driven by"
                  text); each icon names its line on hover, the group reads in full aloud. */}
              {r.lines.length ? (
                <span
                  role="img"
                  data-layer="brain"
                  data-encoding="plain"
                  data-moment-lines={r.lines.join(" ")}
                  aria-label={fmt(T.drivenBy, { lines: names(r.lines) })}
                  className="inline-flex shrink-0 items-center gap-1.5 text-muted-foreground"
                >
                  {r.lines.map((k) => (
                    <span key={k} title={T.lanes[k]} className="inline-flex">
                      <LineIcon line={k} />
                    </span>
                  ))}
                </span>
              ) : null}
              {/* An edge moment is always marked lower confidence (D18). */}
              {r.edge ? (
                <LayerValue layer="brain" encoding="plain" data-edge className="shrink-0 font-mono text-[11px] text-muted-foreground">
                  {T.edge}
                </LayerValue>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p data-layer="ui" className="text-ui text-muted-foreground">
          {T.noMoments}
        </p>
      )}
    </div>
  );
}

/** The key as swatches only (D30): each name shows on hover or tap. */
function Legend({ brain }: { brain: boolean }) {
  const G = T.legend;
  const brainItems = brain
    ? [
        {
          key: "line",
          name: G.line,
          mark: (
            <svg aria-hidden width="18" height="4" viewBox="0 0 18 4" className="overflow-visible">
              <line x1="1" x2="17" y1="2" y2="2" strokeWidth="2" className="brain-line stroke-foreground" />
            </svg>
          ),
        },
        {
          key: "fill",
          name: G.fill,
          mark: (
            <svg aria-hidden width="12" height="10" viewBox="0 0 12 10">
              <rect x="0" y="0" width="12" height="5" className="fill-brain-warm-soft" />
              <rect x="0" y="5" width="12" height="5" className="fill-brain-cool-soft" />
            </svg>
          ),
        },
        {
          key: "high",
          name: G.high,
          mark: (
            <svg aria-hidden width="10" height="9" viewBox="0 0 10 9" className="fill-brain-warm">
              <path d="M0 0H10L5 9Z" />
            </svg>
          ),
        },
        { key: "flat", name: G.flat, mark: <span aria-hidden className="h-1.5 w-4 rounded-sm bg-brain-cool/80" /> },
      ]
    : [];
  return (
    <SwatchLegend
      label={G.label}
      items={[
        ...brainItems,
        { key: "suggested", name: G.suggested, mark: <span aria-hidden className="h-2.5 w-4 rounded-sm border border-indigo-accent" /> },
        { key: "accepted", name: G.accepted, mark: <span aria-hidden className="h-2.5 w-4 rounded-sm border border-line bg-subtle" /> },
        { key: "playhead", name: G.playhead, mark: <span aria-hidden className="h-3 w-px bg-indigo-accent" /> },
      ]}
      className="-mx-1"
    />
  );
}

export function TimelineCard({ reel, brain, view, beats, tEnd, lastSec }: TimelineCardProps) {
  const sc = reel.shortcode;
  const tribe = brain.kind === "read" ? brain.tribe : null;
  const lanes = jobSpec("tribe.lanes");
  const peak = tribe?.peak_image ?? null;
  const peakSrc = `/reels/${encodeURIComponent(sc)}/peak`;
  const hasPeakImage = Boolean(tribe && peak && brain.kind === "read" && brain.image);
  const peakTile: PeakTile | null =
    hasPeakImage && peak
      ? { src: peakSrc, alt: fmt(T.peak.alt, { time: clock(peak.t) }), caption: fmt(T.peak.title, { time: clock(peak.t) }) }
      : null;
  // With no read on show, the action sits right under the axis, outside the slider, so pressing
  // the button never moves the playhead. The pill is the one short line; the longer note waits
  // behind an (i) by the button (D30).
  const emptyStack = (body: string, hintLabel: string, action: ReactNode) => (
    <div data-layer="ui" data-empty-action="" className="flex flex-wrap items-center justify-center gap-2">
      {action}
      <InfoHint label={hintLabel}>{body}</InfoHint>
    </div>
  );
  const empty =
    brain.kind === "none"
      ? emptyStack(
          fmt(T.empty.body, { usd: formatUsd(lanes?.estimate_usd ?? 0), n: JOB_LIMITS.tribe_reads_per_month }),
          T.empty.hintLabel,
          <JobButton
            kind="tribe.lanes"
            args={{ sc }}
            label={jobKindLabel("tribe.lanes")}
            confirmLabel={fmt(copy.reel.actions.tribeConfirm, { sc })}
            size="xs"
          />,
        )
      : brain.kind === "missing"
        ? emptyStack(
            fmt(T.missing.body, { date: brain.date }),
            T.missing.hintLabel,
            <JobButton kind="sync.push" label={jobKindLabel("sync.push")} size="xs" />,
          )
        : undefined;

  return (
    <section id={TIMELINE_ID} className="flex min-h-0 scroll-mt-20 flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-x-3 gap-y-2 border-b border-line px-4 py-2.5">
        <div className="flex min-w-0 flex-col gap-0.5">
          <div data-layer="ui" className="flex items-center gap-2">
            <h2 className="text-ui font-medium">{T.title}</h2>
            <LayerTag layer="shape" />
            <LayerTag layer="brain" />
          </div>
          {/* One small framing chip next to the brain (D30); the scale, the run stamp and the
              notes on this read wait behind its (i). */}
          {tribe ? (
            <div className="flex min-w-0 items-center gap-1.5 text-[11px] leading-4 text-muted-foreground">
              <LayerValue
                layer="brain"
                encoding="plain"
                data-framing=""
                className="truncate rounded-sm border border-dotted border-muted-foreground/60 px-1.5"
              >
                {tribe.framing}
              </LayerValue>
              <InfoHint label={T.notes} layer="brain" align="start">
                <span data-read-notes="" className="flex flex-col gap-1.5">
                  <span>{tribe.scale.label}</span>
                  {reel.stamps.brain ? <span>{reel.stamps.brain}</span> : null}
                  {tribe.warnings.map((w) => (
                    <span key={w.code} className="text-muted-foreground">
                      {w.text}
                    </span>
                  ))}
                </span>
              </InfoHint>
            </div>
          ) : null}
        </div>
        {brain.kind !== "none" ? (
          <JobButton
            kind="tribe.lanes"
            args={{ sc }}
            label={jobKindLabel("tribe.lanes")}
            confirmLabel={fmt(copy.reel.actions.tribeConfirm, { sc })}
            size="xs"
          />
        ) : null}
      </header>

      {/* On a laptop the card is a pane (Grain): the header stays, the rest scrolls inside it. */}
      <div className="min-h-0 lg:overflow-y-auto lg:overscroll-contain lg:[scrollbar-width:thin]">
        {view ? <BrainSection view={view} endLabel={clock(Math.min(lastSec + 1, tEnd))} peak={peakTile} /> : null}

        <div className="px-4 pt-3 pb-4">
          <ReelTimeline
            tEnd={tEnd}
            beats={beats}
            brain={tribe ? toBrain(tribe) : null}
            emptyPill={brain.kind === "missing" ? T.missing.pill : brain.kind === "none" ? T.empty.pill : undefined}
            empty={empty}
            legend={<Legend brain={Boolean(tribe)} />}
          />
        </div>

        {tribe ? <Moments tribe={tribe} lastSec={lastSec} /> : null}

        {!view && hasPeakImage && peak ? (
          <figure className="flex flex-col gap-1.5 border-t border-line px-4 py-3">
            <figcaption data-layer="ui" className="text-[11px] leading-4 font-medium">
              {fmt(T.peak.title, { time: clock(peak.t) })}
            </figcaption>
            <Image
              data-layer="brain"
              src={peakSrc}
              alt={fmt(T.peak.alt, { time: clock(peak.t) })}
              width={480}
              height={240}
              unoptimized
              className="h-auto w-full max-w-sm rounded-md border border-line"
            />
          </figure>
        ) : null}

        {view ? <BrainCredits className="border-t border-line px-4 py-2" /> : null}

        {/* A laptop-only cue that more sits below: a surface fade (borders, not shadows) that
            covers only this spacer once the pane is scrolled to its end. */}
        <div aria-hidden className="hidden h-6 lg:block" />
        <div
          aria-hidden
          data-layer="ui"
          className="pointer-events-none sticky bottom-0 -mt-6 hidden h-6 bg-linear-to-t from-surface to-surface/0 lg:block"
        />
      </div>
    </section>
  );
}
