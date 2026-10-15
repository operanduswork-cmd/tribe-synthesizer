// What the reel page hands the 3D brain, the Areas tab and the downloads (D28): a small, plain
// object built on the server from the schema-checked brain page that belongs to this reel (lib/data.ts
// getReelBrain, D21). The heavy parts stay behind their own routes: the frames, mesh and atlas
// (binary, lazy) and the per-area series (JSON, loaded when the Areas tab first opens or the
// brain is first hovered). Only the seven network series and the atlas tables ride along, so
// the Areas tab can draw its first rows at once. Pure: safe on the server and in the browser.

import type { LineKey } from "@/components/reel/time";
import { brainUrls } from "@/lib/brain/format";
import type { BrainPage, TribePage } from "@/lib/hosted.gen";

export type BrainView = {
  sc: string;
  jobId: string;
  /** The read's seconds, one per frame row. */
  timeS: number[];
  /** The one colour scale for this whole reel: model output at the 99th percentile of |x|. */
  vmax: number;
  /** |value| / vmax below this shows grey only (the "coloured on the brain" threshold). */
  greyBelow: number;
  /** |value| / vmax at or above this shows full colour. */
  fullAt: number;
  urls: { mesh: string; atlas: string; frames: string; areas: string; csv: string };
  /** Decompressed sizes, for the load progress. */
  bytes: { mesh: number; atlas: number; frames: number };
  atlas: {
    /** HCP-MMP1 short codes, in atlas.hcp.labels order (index k; the lookup value is k + 1). */
    codes: string[];
    /** Yeo-7 network (1..7) per HCP area: the network that holds most of its points. */
    network: number[];
    /** Which of the four lines each HCP area feeds, or null. */
    line: Array<LineKey | null>;
    /** The fixed display order: Yeo network, then Glasser index. Never sorted by a value. */
    order: number[];
    /** Yeo-7 names, verbatim ("Yeo network 5: Limbic"). */
    yeo: string[];
  };
  /** Yeo-7 series [7][T] (area means, 4 dp), for the Areas tab's first paint. */
  networks: number[][];
  /** HIGH seconds of the read (warm ticks on the brain scrubber). */
  highs: Array<{ t: number; edge: boolean }>;
};

export function brainView(sc: string, brain: BrainPage, tribe: TribePage): BrainView {
  return {
    sc,
    jobId: brain.job_id,
    timeS: brain.time_s,
    vmax: brain.scale.vmax,
    greyBelow: brain.scale.grey_below,
    fullAt: brain.scale.full_at,
    urls: {
      mesh: brainUrls.mesh(brain.mesh),
      atlas: brainUrls.atlas(brain.atlas),
      frames: brainUrls.frames(sc, brain.frames),
      areas: brainUrls.areas(sc, brain.frames),
      csv: brainUrls.csv(sc),
    },
    bytes: { mesh: brain.mesh.bytes, atlas: brain.atlas.bytes, frames: brain.frames.bytes },
    atlas: {
      codes: [...brain.atlas.hcp.labels],
      network: brain.atlas.hcp.network,
      line: brain.atlas.hcp.line,
      order: brain.atlas.order,
      yeo: [...brain.atlas.yeo.labels],
    },
    networks: brain.areas.yeo,
    highs: tribe.peaks.map((p) => ({ t: p.t, edge: p.edge })),
  };
}

/** Where a value sits on the reel's one scale: coloured warm, coloured cool, or grey. The same
 *  threshold as the 3D colours (scale.grey_below), never a per-area scale. */
export type OnBrain = "above" | "below" | "none";

export function onBrain(value: number | null | undefined, view: Pick<BrainView, "vmax" | "greyBelow">): OnBrain {
  if (typeof value !== "number" || !Number.isFinite(value) || view.vmax <= 0) return "none";
  if (Math.abs(value) / view.vmax < view.greyBelow) return "none";
  return value > 0 ? "above" : "below";
}

/** The row of a series for whole second t, or -1 when the read has no such second. */
export function rowAt(timeS: number[], t: number | null): number {
  if (t === null) return -1;
  return timeS.findIndex((s) => Math.floor(s) === t);
}
