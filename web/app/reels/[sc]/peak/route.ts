// The peak brain picture of a reel's TRIBE read (peak.png, pushed by strategist.sync after
// strategist.hosted checked it is a PNG under 1 MB). Only the map of the predicted average-brain
// response: no video stills, which stay on the laptop. 404 when there is no read or no picture.

import { getImage, getReel, getTribe } from "@/lib/data";

const SC_RE = /^[A-Za-z0-9_-]{5,20}$/;
const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
const MAX_BYTES = 1024 * 1024;

const notFound = () => new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });

export async function GET(_req: Request, ctx: RouteContext<"/reels/[sc]/peak">) {
  const { sc } = await ctx.params;
  if (!SC_RE.test(sc)) return notFound();
  const reel = await getReel(sc).catch(() => null);
  if (!reel?.tribe || reel.tribe.missing) return notFound();
  const tribe = await getTribe(reel.tribe.job_id).catch(() => null);
  if (!tribe?.peak_image || (tribe.shortcode !== null && tribe.shortcode !== sc)) return notFound();
  const bytes = await getImage(tribe.peak_image.key).catch(() => null);
  if (!bytes || bytes.length > MAX_BYTES || !PNG.every((b, i) => bytes[i] === b)) return notFound();
  return new Response(new Uint8Array(bytes), {
    headers: {
      "Content-Type": "image/png",
      "Cache-Control": "private, max-age=300",
      "Content-Disposition": "inline",
    },
  });
}
