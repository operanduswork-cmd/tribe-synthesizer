// The shared fsaverage5 inflated mesh (TBM1, gzip as stored) the brain view draws every read on.
// It names no reel and holds no reel's data, so any read's page may point at it. Served only
// when it is stored, whole and named by the URL's ?h= (the first 8 hex digits of its sha256,
// lib/brain/format.ts brainUrls.mesh), so the immutable cache can never go stale; 404 otherwise.

import { rawSize } from "@/lib/brain/format";
import { assetProblem, assetResponse, hashParamMatches, notFound } from "@/lib/brain/serve";
import { getBrainAsset } from "@/lib/data";

const VERSION_RE = /^v\d{1,3}$/;

export async function GET(req: Request, ctx: RouteContext<"/brain/mesh/[version]">) {
  const { version } = await ctx.params;
  if (!VERSION_RE.test(version)) return notFound();
  const asset = await getBrainAsset(`shared/fsaverage5-inflated-${version}.bin`).catch(() => null);
  if (!asset || !hashParamMatches(req, asset.hash)) return notFound();
  if (assetProblem(asset, { key: asset.key, sha256: asset.hash, bytes: rawSize("mesh") }, "mesh")) return notFound();
  return assetResponse(asset);
}
