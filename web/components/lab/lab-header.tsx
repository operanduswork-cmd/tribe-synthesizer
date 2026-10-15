// The draft's header: its title (with a small Example chip on the example draft) and the run
// buttons. Check runs now (stage 1); This but… and Replace X with Y open their rewrite panels (the
// /script command works today, the site button is stage 2); New draft is stage 2. No stamps here:
// when it was checked sits at the top of the checks rail. A stale or never-checked draft gets a
// dashed note under the header.

import { RefinePopover } from "@/components/lab/refine-popover";
import { JobButton } from "@/components/shared/job-button";
import { LayerValue } from "@/components/shared/layer-value";
import { PageHeader } from "@/components/shared/page-header";
import { copy } from "@/lib/copy";
import type { LabPage } from "@/lib/hosted";
import { jobKindLabel } from "@/lib/job-kinds";

export function LabHeader({ lab }: { lab: LabPage }) {
  return (
    <PageHeader
      title={<LayerValue layer="ui">{lab.title}</LayerValue>}
      subtitle={
        lab.kind === "example" ? (
          <LayerValue layer="ui" className="rounded-sm border border-line px-1.5 font-mono text-mono">
            {copy.lab.header.example}
          </LayerValue>
        ) : undefined
      }
      actions={
        <>
          <JobButton kind="lab.check" args={{ draft_id: lab.id }} label={jobKindLabel("lab.check")} variant="default" />
          <RefinePopover mode="this_but" draftId={lab.id} command={lab.commands.this_but} />
          <RefinePopover mode="replace" draftId={lab.id} command={lab.commands.replace} />
          <JobButton kind="coach.new_draft" args={{ slug: lab.slug }} label={jobKindLabel("coach.new_draft")} />
        </>
      }
    >
      {lab.stale ? (
        <LayerValue as="p" layer="ui" className="rounded-md border border-dashed border-foreground/40 px-3 py-2 text-[13px] leading-5">
          {lab.stale}
        </LayerValue>
      ) : null}
    </PageHeader>
  );
}
