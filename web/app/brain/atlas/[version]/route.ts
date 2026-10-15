// The shared atlas lookups (TBA1, gzip as stored): which HCP-MMP1 area and Yeo-7 network each
// surface point belongs to. Derived HCP data (CREDITS.md section 4): private, behind the login,
// never shared. It names no reel. Served only when it is stored, whole and named by the URL's ?h=
// (lib/brain/format.ts brainUrls.atlas), so the immutable cache can never go stale; 404 otherwise.

import { rawSize } from "@/lib/brain/format";
import { assetProblem, assetResponse, hashParamMatches, notFound } from "@/lib/brain/serve";
import { getBrainAsset } from "@/lib/data";

const VERSION_RE = /^v\d{1,3}$/;

export async function GET(req: Request, ctx: RouteContext<"/brain/atlas/[version]">) {
  const { version } = await ctx.params;
  if (!VERSION_RE.test(version)) return notFound();
  const asset = await getBrainAsset(`shared/atlas-${version}.bin`).catch(() => null);
  if (!asset || !hashParamMatches(req, asset.hash)) return notFound();
  if (assetProblem(asset, { key: asset.key, sha256: asset.hash, bytes: rawSize("atlas") }, "atlas")) return notFound();
  return assetResponse(asset);
}
