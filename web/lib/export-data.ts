// The export body, built once for both the download (app/export/data/route.ts) and the preview on
// /export, so the two cannot drift. Server-side only. Four top-level keys that never share an
// object: "meta" (framing, licence), "reels" (counts and shape layers of the visible board rows),
// "patterns" and "brain" (one object per reel with a read; no ranking, nothing across reels, D20,
// D21). No words, transcripts, captions, stills or video (D30).

import { connection } from "next/server";

import { copy, fmt } from "@/lib/copy";
import { getBoard, getPatterns, getReel, getReelBrain } from "@/lib/data";

/** The export as an object, or null when the board is not available. */
export async function buildExport() {
  await connection(); // the made-on date is the request time: never prerendered
  const board = await getBoard().catch(() => null);
  if (!board) return null;
  const patterns = await getPatterns().catch(() => null);

  const reels = await Promise.all(
    board.reels.map(async (r) => {
      const page = await getReel(r.sc).catch(() => null);
      return {
        shortcode: r.sc,
        handle: r.handle,
        duration_s: r.sort.duration,
        plays: r.sort.plays,
        posted: r.cells.posted,
        x_own_median: r.sort.x,
        shape: {
          hook: r.cells.hook,
          format: r.cells.format,
          cta: r.cells.cta,
          beats: (page?.beats ?? []).map((b) => b.name),
        },
      };
    }),
  );

  const brain = (await Promise.all(board.reels.map((r) => getReelBrain(r.sc).catch(() => null))))
    .filter((hit) => hit !== null)
    .map(({ reel, brain: b }) => ({
      shortcode: reel.shortcode,
      job_id: b.job_id,
      framing: b.framing,
      time_s: b.time_s,
      atlas: { version: b.atlas.version, hcp_labels: b.atlas.hcp.labels, order: b.atlas.order, yeo_labels: b.atlas.yeo.labels },
      areas: b.areas,
    }));

  return {
    meta: {
      framing: copy.export.framing,
      note: fmt(copy.export.note, { date: new Date().toISOString().slice(0, 10) }),
      licence: copy.export.licence,
      built_with: copy.footer.llama,
    },
    reels,
    patterns,
    brain,
  };
}

/** The exact text of the download: 2-space pretty-printed JSON. */
export async function buildExportText(): Promise<{ text: string; reels: number; brain: number } | null> {
  const body = await buildExport();
  if (!body) return null;
  return { text: JSON.stringify(body, null, 2), reels: body.reels.length, brain: body.brain.length };
}
