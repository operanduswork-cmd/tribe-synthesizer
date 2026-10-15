// A reel's private video (D30): a 302 to a signed link into the private Blob store, valid about
// 20 minutes (lib/reel-video.ts), never cached (private, no-store), so the page asks again when a
// link has run out. The store's own token never leaves the server. 404 when the shortcode is
// malformed, the reel has no video, or the site runs on fixtures (no Blob store there; the tests
// serve a synthetic clip in place of this route). 503 when the link cannot be signed.

import { REEL_VIDEO_PATHNAME_RE } from "@/db/schema";
import { dataSource, getReelVideo } from "@/lib/data";
import { presignReelVideo } from "@/lib/reel-video";

const SC_RE = /^[A-Za-z0-9_-]{5,20}$/;
const PATHNAME_RE = new RegExp(REEL_VIDEO_PATHNAME_RE);
const NO_STORE = { "Cache-Control": "private, no-store" };

const status = (code: 404 | 503) => new Response(null, { status: code, headers: NO_STORE });

export async function GET(_req: Request, ctx: RouteContext<"/reels/[sc]/video">) {
  const { sc } = await ctx.params;
  if (!SC_RE.test(sc) || dataSource() !== "db") return status(404);
  const row = await getReelVideo(sc).catch(() => null);
  if (!row || row.shortcode !== sc || !PATHNAME_RE.test(row.pathname) || !row.pathname.startsWith(`reels/${sc}-`)) {
    return status(404);
  }
  let location: string;
  try {
    location = await presignReelVideo(row.pathname);
  } catch (e) {
    // The error class only: a message could carry a link.
    console.error(`reel video: could not sign a link (${e instanceof Error ? e.name : "unknown"})`);
    return status(503);
  }
  return new Response(null, { status: 302, headers: { Location: location, ...NO_STORE } });
}
