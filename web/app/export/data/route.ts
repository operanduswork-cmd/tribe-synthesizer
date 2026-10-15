// "Download JSON": everything the hosted pages hold, as one file, built here from the
// schema-checked pages (lib/data.ts), never stored. A private download, never cached. Four
// top-level keys that never share an object: "meta" (framing, licence), "reels" (the counts and
// shape layers of the visible board rows), "patterns" (the patterns page as hosted) and "brain"
// (one object per reel with a read: its per-second area means in fixed atlas order, exactly as the
// areas route and the CSV give them; no ranking, nothing across reels, D20, D21). No words,
// transcripts, captions, stills or video (D30). Same shape as ../../reels/[sc]/brain/csv/route.ts.

import { copy, fmt } from "@/lib/copy";
import { getBoard, getPatterns, getReel, getReelBrain } from "@/lib/data";

export async function GET() {
  const board = await getBoard().catch(() => null);
  if (!board) return new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });
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

  const body = {
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
  return new Response(JSON.stringify(body, null, 1), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Disposition": 'attachment; filename="tribe-export.json"',
      "Cache-Control": "private, no-store",
    },
  });
}
