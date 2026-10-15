// Export (Round 6, preview Round 7): a raw JSON preview of exactly what the download gives, with
// Copy and Download beside it. Built server-side by the same function as app/export/data/route.ts
// (lib/export-data.ts), so the page and the file cannot drift. The one explanation sits behind an (i).

import type { Metadata } from "next";
import { Suspense } from "react";

import { JsonPreview } from "@/components/export/json-preview";
import { InfoHint } from "@/components/shared/info-hint";
import { PageHeader } from "@/components/shared/page-header";
import { copy } from "@/lib/copy";
import { buildExportText } from "@/lib/export-data";

export const metadata: Metadata = { title: copy.pages.export.title };

async function Preview() {
  const built = await buildExportText();
  if (!built) return <p className="text-sm text-muted-foreground">{copy.export.unavailable}</p>;
  return (
    <div className="flex items-start gap-1.5">
      <div className="min-w-0 flex-1">
        <JsonPreview text={built.text} reels={built.reels} brain={built.brain} />
      </div>
      <InfoHint label={copy.export.hintLabel}>{copy.export.hint}</InfoHint>
    </div>
  );
}

export default function ExportPage() {
  return (
    <div data-page="export" className="page-wash mx-auto w-full min-w-0 max-w-[1400px]">
      <PageHeader title={copy.pages.export.title} />
      <Suspense fallback={null}>
        <Preview />
      </Suspense>
    </div>
  );
}
