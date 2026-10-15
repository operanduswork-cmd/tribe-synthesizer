// The reel screen (Grain reference): the left column has the tabs Card / Beats / Areas / Facts
// (Areas only with a brain page, D28), the right column the reel's own video with its sound (D30,
// when one is stored; it is the page's clock) over a sticky card with the 3D brain and the
// timeline with one track per lane. Under 1024px it is one column: the video first, then the card
// (D18: the short card comes before the rest), then the timeline full width with its playhead
// (YouTube Studio). Counts and the brain layer never share a line, chart or total (D20):
// counts sit in the strip above the card and in their own chart; the timeline holds shape and
// brain only. Private details (transcript, stills, quotes) stay on the laptop: a lock button in
// the header opens the laptop commands (round 3, D30: labels and values stay, the rest sits
// behind (i) hints).

import { ArrowUpRightIcon } from "lucide-react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { AreasPanel } from "@/components/reel/areas-panel";
import { BeatsPanel } from "@/components/reel/beats-panel";
import { brainView, type BrainView } from "@/components/reel/brain/view";
import { CountsBlock } from "@/components/reel/counts-block";
import { FactsPanel } from "@/components/reel/facts-panel";
import { CountsStrip, PrivateButton, SnippetCard } from "@/components/reel/reel-card";
import { ReelTabs } from "@/components/reel/reel-tabs";
import { ReelTimeProvider } from "@/components/reel/reel-time";
import type { TimelineBeat } from "@/components/reel/reel-timeline";
import { ReelVideo } from "@/components/reel/reel-video";
import { parseChip } from "@/components/reel/time";
import { TimelineCard, type BrainState } from "@/components/reel/timeline-card";
import { LayerValue } from "@/components/shared/layer-value";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/page-skeleton";
import { copy, fmt } from "@/lib/copy";
import { dataSource, getBoard, getReel, getReelBrain, getReelVideo, getTribe } from "@/lib/data";
import type { ReelPage } from "@/lib/hosted";

export const metadata: Metadata = { title: copy.pages.reel.title };

const R = copy.reel;

export default function ReelRoute({ params }: PageProps<"/reels/[sc]">) {
  return (
    <Suspense fallback={<PageSkeleton rows={8} />}>
      <ReelContent params={params} />
    </Suspense>
  );
}

/** The brain side: a read on this reel's own scale, a read the laptop has not pushed, or none.
 *  A read that names another reel is never shown here (D21: never across reels). */
async function loadBrain(reel: ReelPage): Promise<BrainState> {
  if (!reel.tribe) return { kind: "none" };
  const missing: BrainState = { kind: "missing", date: reel.tribe.run_date };
  if (reel.tribe.missing) return missing;
  const tribe = await getTribe(reel.tribe.job_id).catch(() => null);
  if (!tribe || (tribe.shortcode !== null && tribe.shortcode !== reel.shortcode)) return missing;
  return { kind: "read", tribe, image: dataSource() === "db" && tribe.peak_image !== null };
}

/** The drawn time axis: the read's clip length, else the Length fact, never shorter than the beats. */
function axisOf(reel: ReelPage, brain: BrainState, beats: TimelineBeat[]): { tEnd: number; lastSec: number } {
  let tEnd = Math.max(1, ...beats.map((b) => b.end));
  if (brain.kind === "read") {
    const ts = brain.tribe.time_s;
    tEnd = Math.max(tEnd, brain.tribe.clip_s, ts.length ? ts[ts.length - 1] + 1 : 0);
  } else {
    const length = parseChip(reel.facts.find((f) => f.label === "Length")?.value);
    if (length) tEnd = Math.max(tEnd, length.start);
  }
  return { tEnd, lastSec: Math.max(0, Math.ceil(tEnd - 1e-6) - 1) };
}

/** The second the page opens on: the read's first HIGH away from the clip's edges (D28), so the
 *  timeline and the brain start on a moment; null without a read or without such a HIGH. */
function firstHigh(brain: BrainState, lastSec: number): number | null {
  if (brain.kind !== "read") return null;
  const ts = brain.tribe.peaks.filter((p) => !p.edge).map((p) => p.t);
  return ts.length ? Math.min(lastSec, Math.max(0, Math.min(...ts))) : null;
}

async function ReelContent({ params }: { params: PageProps<"/reels/[sc]">["params"] }) {
  const { sc } = await params;
  const reel = await getReel(sc);
  if (!reel) notFound();

  const [board, brain, reelBrain, video] = await Promise.all([
    getBoard().catch(() => null),
    loadBrain(reel),
    // The 3D brain and the Areas tab: only a brain page that names this reel's own read (D21).
    reel.tribe && !reel.tribe.missing ? getReelBrain(reel.shortcode).catch(() => null) : null,
    // The reel's private video (D30), when strategist.media pushed one.
    getReelVideo(reel.shortcode).catch(() => null),
  ]);
  const view: BrainView | null =
    reelBrain && brain.kind === "read" && reelBrain.tribe.job_id === brain.tribe.job_id
      ? brainView(reel.shortcode, reelBrain.brain, reelBrain.tribe)
      : null;
  const row = board?.reels.find((r) => r.sc === reel.shortcode) ?? null;
  const beats: TimelineBeat[] = reel.beats.flatMap((b) => {
    const span = parseChip(b.chip);
    return span ? [{ ...span, kind: b.kind, name: b.name, suggested: b.suggested }] : [];
  });
  const { tEnd, lastSec } = axisOf(reel, brain, beats);
  const handle = "@" + reel.owner;
  const posted = reel.posted ? fmt(R.posted, { date: reel.posted }) : R.notDated;

  // Round 3 (D30, less text): under the handle only the post date (named on hover) and an icon
  // link to the post; the lock button for the laptop-only details sits on the right (D31: analysis only, no Recreate).
  return (
    <>
      <PageHeader
        title={<LayerValue layer="ui">{handle}</LayerValue>}
        subtitle={
          <span className="inline-flex items-center gap-1.5">
            <LayerValue layer="ui" title={posted} className="font-mono text-mono">
              {reel.posted ?? R.notDated}
            </LayerValue>
            <a
              href={reel.url}
              target="_blank"
              rel="noreferrer"
              data-layer="ui"
              data-instagram-link=""
              aria-label={R.instagram}
              title={R.instagram}
              className="tap-target inline-flex size-5 items-center justify-center rounded-sm transition-colors hover:text-foreground"
            >
              <ArrowUpRightIcon aria-hidden className="size-3.5" />
            </a>
          </span>
        }
        actions={<PrivateButton localCmd={reel.local_cmd} />}
      />

      <ReelTimeProvider lastSec={lastSec} initialT={firstHigh(brain, lastSec)}>
        <div className="grid gap-6 lg:grid-cols-[minmax(0,11fr)_minmax(0,9fr)] lg:items-start">
          <div className="min-w-0 max-lg:order-1">
            <ReelTabs
              panels={{
                card: (
                  <>
                    <CountsStrip counts={reel.card.counts} />
                    <SnippetCard card={reel.card} />
                    <CountsBlock sc={reel.shortcode} row={row} discount={reel.discount} />
                  </>
                ),
                beats: <BeatsPanel reel={reel} row={row} />,
                areas: view ? <AreasPanel view={view} /> : undefined,
                facts: <FactsPanel reel={reel} />,
              }}
            />
          </div>
          {/* The video sits on top of this column on a laptop, above the brain; under 1024px the
              column dissolves into the page's one column (display: contents) and the video goes
              first, before the card (D30). */}
          <div className="min-w-0 max-lg:contents lg:sticky lg:top-[calc(var(--shell-topbar)+1.5rem)] lg:flex lg:max-h-[calc(100dvh-var(--shell-topbar)-3rem)] lg:flex-col lg:gap-3">
            {video ? <ReelVideo sc={reel.shortcode} className="shrink-0 max-lg:order-first" /> : null}
            <TimelineCard reel={reel} brain={brain} view={view} beats={beats} tEnd={tEnd} lastSec={lastSec} />
          </div>
        </div>
      </ReelTimeProvider>
    </>
  );
}
