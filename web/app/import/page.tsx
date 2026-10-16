// Import (demo, 16 Oct): paste reel links and see how the results will look. Made-up numbers from
// the link, no job and no spend. The real import stays in the terminal (reel.add_link / add_handle).

import type { Metadata } from "next";

import { ImportDemo } from "@/components/import/import-demo";
import { PageHeader } from "@/components/shared/page-header";
import { copy } from "@/lib/copy";

export const metadata: Metadata = { title: copy.pages.import.title };

export default function ImportPage() {
  return (
    <div data-page="import" className="page-wash mx-auto w-full min-w-0 max-w-[1100px]">
      <PageHeader title={copy.pages.import.title} subtitle={copy.import.intro} />
      <ImportDemo />
    </div>
  );
}
