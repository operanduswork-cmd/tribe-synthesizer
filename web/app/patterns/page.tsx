// Patterns: shapes that repeat across the swipe file, outliers vs normal reels per shape.
// The header (title and Rebuild only, no subtitle: round 3 text cut) renders at once; the data
// part sits in <Suspense> (Cache Components) and reads through lib/data.ts. Layout notes are in
// components/patterns.

import { HammerIcon } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";

import { PatternsEmpty } from "@/components/patterns/patterns-empty";
import { PatternsView } from "@/components/patterns/patterns-view";
import { JobButton } from "@/components/shared/job-button";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/page-skeleton";
import { copy } from "@/lib/copy";
import { getMeta, getPatterns } from "@/lib/data";

export const metadata: Metadata = { title: copy.pages.patterns.title };

export default function PatternsPage() {
  return (
    <>
      <PageHeader
        className="page-wash"
        title={copy.pages.patterns.title}
        actions={<JobButton kind="patterns.build" label={copy.patterns.rebuild} icon={<HammerIcon />} />}
      />
      <Suspense fallback={<PageSkeleton rows={6} />}>
        <PatternsContent />
      </Suspense>
    </>
  );
}

async function PatternsContent() {
  const [patterns, meta] = await Promise.all([getPatterns(), getMeta()]);
  if (!patterns || patterns.patterns.length === 0) return <PatternsEmpty reels={meta?.n.reels ?? 0} />;
  return <PatternsView page={patterns} />;
}
