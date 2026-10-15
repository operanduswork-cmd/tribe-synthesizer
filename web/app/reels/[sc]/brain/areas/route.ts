// One reel's per-area series for the Areas tab (lib/brain/format.ts BrainAreasPayload), loaded
// when the tab first opens: the brain page's seconds and area means (HCP-MMP1 per side, Yeo-7,
// the four lines), rows in atlas.hcp.labels order. 404 unless the reel, its read and its tribe and
// brain pages agree (D21, lib/data.ts getReelBrain) and the URL's ?h= names this read's frames,
// so the series and the frames always come from one build. Same shape as ../../peak/route.ts.

import type { BrainAreasPayload } from "@/lib/brain/format";
import { hashParamMatches, notFound, SC_RE } from "@/lib/brain/serve";
import { getReelBrain } from "@/lib/data";

export async function GET(req: Request, ctx: RouteContext<"/reels/[sc]/brain/areas">) {
  const { sc } = await ctx.params;
  if (!SC_RE.test(sc)) return notFound();
  const hit = await getReelBrain(sc).catch(() => null);
  if (!hit || !hashParamMatches(req, hit.brain.frames.sha256)) return notFound();
  const body: BrainAreasPayload = { job_id: hit.brain.job_id, time_s: hit.brain.time_s, areas: hit.brain.areas };
  return Response.json(body, { headers: { "Cache-Control": "private, max-age=31536000, immutable" } });
}
