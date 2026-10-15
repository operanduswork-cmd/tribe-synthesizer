// "Raw numbers (CSV)": one reel's area numbers, built here from the schema-checked brain page
// (lib/brain/csv.ts), never stored. Derived HCP data (CREDITS.md section 4): a private download,
// never cached. 404 unless the reel, its read and its tribe and brain pages agree (D21, lib/data.ts
// getReelBrain), and when a cell would be doubtful. Same shape as ../../peak/route.ts.

import { areasCsv, areasCsvFilename } from "@/lib/brain/csv";
import { notFound, SC_RE } from "@/lib/brain/serve";
import { getReelBrain } from "@/lib/data";

export async function GET(_req: Request, ctx: RouteContext<"/reels/[sc]/brain/csv">) {
  const { sc } = await ctx.params;
  if (!SC_RE.test(sc)) return notFound();
  const hit = await getReelBrain(sc).catch(() => null);
  if (!hit) return notFound();
  let body: string;
  try {
    body = areasCsv(hit.brain, sc, hit.tribe.run_date);
  } catch {
    return notFound();
  }
  return new Response(body, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="${areasCsvFilename(sc, hit.brain.job_id)}"`,
      "Cache-Control": "private, no-store",
    },
  });
}
