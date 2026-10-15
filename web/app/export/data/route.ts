// "Download JSON": everything the hosted pages hold, as one file, built by lib/export-data.ts (the
// same builder the preview on /export uses) from the schema-checked pages, never stored. A private
// download, never cached. Shape notes live in that file.

import { buildExportText } from "@/lib/export-data";

export async function GET() {
  const built = await buildExportText();
  if (!built) return new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });
  return new Response(built.text, {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Disposition": 'attachment; filename="tribe-export.json"',
      "Cache-Control": "private, no-store",
    },
  });
}
