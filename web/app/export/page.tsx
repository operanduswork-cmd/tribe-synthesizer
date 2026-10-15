// Export (Round 6): one button that downloads everything the hosted pages hold as one JSON file
// (app/export/data/route.ts). Minimal text; the one explanation sits behind an (i).

import type { Metadata } from "next";

import { InfoHint } from "@/components/shared/info-hint";
import { PageHeader } from "@/components/shared/page-header";
import { buttonVariants } from "@/components/ui/button";
import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: copy.pages.export.title };

export default function ExportPage() {
  return (
    <div data-page="export" className="mx-auto w-full max-w-[1400px]">
      <PageHeader title={copy.pages.export.title} />
      <div className="flex items-center gap-1.5">
        {/* A plain link with download: no script needed, works on a phone. */}
        <a
          href="/export/data"
          download
          data-export-download=""
          className={cn(buttonVariants({ variant: "default", size: "lg" }), "min-h-11 px-4")}
        >
          {copy.export.button}
        </a>
        <InfoHint label={copy.export.hintLabel}>{copy.export.hint}</InfoHint>
      </div>
    </div>
  );
}
