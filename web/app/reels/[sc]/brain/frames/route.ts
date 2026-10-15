// One reel's brain frames (TBF1, gzip as stored): the predicted average-brain response per second
// and surface point, int8 on ONE colour scale for this reel (D28). 404 unless the reel has a read
// and its tribe and brain pages name the same job, reel and seconds (D21, lib/data.ts
// getReelBrain), the URL's ?h= names the frames the page names, and the stored bytes are exactly
// those frames (lib/brain/serve.ts). Same shape as ../../peak/route.ts.

import { assetProblem, assetResponse, hashParamMatches, notFound, SC_RE } from "@/lib/brain/serve";
import { getBrainAsset, getReelBrain } from "@/lib/data";

export async function GET(req: Request, ctx: RouteContext<"/reels/[sc]/brain/frames">) {
  const { sc } = await ctx.params;
  if (!SC_RE.test(sc)) return notFound();
  const hit = await getReelBrain(sc).catch(() => null);
  if (!hit || !hashParamMatches(req, hit.brain.frames.sha256)) return notFound();
  const asset = await getBrainAsset(hit.brain.frames.key).catch(() => null);
  if (!asset || assetProblem(asset, hit.brain.frames, "frames", hit.brain.time_s.length)) return notFound();
  return assetResponse(asset);
}
