// The queue (Vercel deployments / GitHub Actions runs references): one 36px row per job (44px on
// touch) that leads with its status as an ink glyph and a word, never a coloured block; the job
// and its details in mono; the cost; when it was queued. Rows fade in one after another. A row
// opens (Mintlify previews) with an ink rule down its left edge to its progress lines as a small
// timeline, the refusal or error code, and Confirm / Cancel while it is live.

import { ChevronRightIcon } from "lucide-react";

import { JobActions } from "@/components/settings/job-actions";
import { JobStatusMark } from "@/components/settings/status-mark";
import { LayerValue } from "@/components/shared/layer-value";
import { RelativeTime } from "@/components/shared/relative-time";
import { copy, fmt } from "@/lib/copy";
import type { JobRow } from "@/lib/data";
import { formatUsd, formatUtc } from "@/lib/format";
import { jobKindLabel, jobSpec } from "@/lib/job-kinds";
import { cn } from "@/lib/utils";

const COLS = "md:grid md:grid-cols-[7.5rem_minmax(0,1fr)_10rem_6.5rem_1rem] md:items-center md:gap-3";

/** The stagger step for row i, capped so a long queue does not trickle in. */
const stagger = (i: number) => ({ animationDelay: `calc(${Math.min(i, 8)} * var(--motion-stagger))` });

/** "Free", "Free, uses the Claude plan" or "about $0.10". */
function costText(job: JobRow): string {
  const spec = jobSpec(job.kind);
  if (spec?.paid || job.estimateUsd > 0) return fmt(copy.jobs.estimate, { usd: formatUsd(job.estimateUsd) });
  return spec?.billing === "claude_plan" ? copy.jobs.claudePlan : copy.jobs.free;
}

/** The job's arguments as one mono line ("DEMO0000001 · all"). A job with no arguments shows none. */
function argsText(job: JobRow): string {
  return Object.values(job.args)
    .map((v) => (typeof v === "string" ? v : JSON.stringify(v)))
    .join(` ${copy.lab.header.sep} `);
}

/** "09:40:02" in UTC from an ISO string (a stored time, not the clock). */
function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString().slice(11, 19);
}

export function JobListHeader() {
  const c = copy.settings.queue.columns;
  return (
    <div data-layer="ui" aria-hidden className={cn("hidden h-8 border-b border-line px-3 text-[11px] text-muted-foreground", COLS)}>
      <span>{c.status}</span>
      <span>{c.job}</span>
      <span>{c.cost}</span>
      <span>{c.queued}</span>
      <span />
    </div>
  );
}

export function JobList({ jobs }: { jobs: JobRow[] }) {
  return (
    <ul data-jobs className="flex flex-col divide-y divide-line">
      {jobs.map((job, i) => (
        <JobItem key={job.id} job={job} index={i} />
      ))}
    </ul>
  );
}

/** The progress lines as a small timeline: a dot per line on a hairline, the latest one filled. */
function Progress({ events }: { events: JobRow["events"] }) {
  if (!events.length) return <p className="text-[13px] leading-5 text-muted-foreground">{copy.settings.queue.noProgress}</p>;
  return (
    <ol className="flex flex-col">
      {events.map((e, i) => {
        const last = i === events.length - 1;
        return (
          <li
            key={i}
            data-row
            className="relative flex items-baseline gap-3 pb-1.5 pl-4 text-[13px] leading-5 group-open:animate-appear last:pb-0"
            style={stagger(i)}
          >
            {last ? null : <span aria-hidden className="absolute top-[14px] -bottom-[7px] left-[3px] w-px bg-line" />}
            <span
              aria-hidden
              className={cn("absolute top-[7px] left-0 size-[7px] rounded-full border border-foreground", last ? "bg-foreground" : "bg-surface")}
            />
            <LayerValue layer="ui" className="shrink-0 font-mono text-[12px] leading-4 text-muted-foreground tabular-nums">
              {clock(e.at)}
            </LayerValue>
            <LayerValue layer="ui">{e.line}</LayerValue>
          </li>
        );
      })}
    </ol>
  );
}

function JobItem({ job, index }: { job: JobRow; index: number }) {
  const label = jobKindLabel(job.kind);
  const spec = jobSpec(job.kind);
  const live = job.status === "queued" || job.status === "running";
  const needsConfirm = Boolean(spec?.paid) && job.status === "queued" && !job.confirmedAt && !job.cancelRequested;
  return (
    <li data-row data-job={job.id} data-status={job.status} className="relative animate-appear" style={stagger(index)}>
      <details className="group">
        <summary
          className={cn(
            "flex min-h-9 cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-1.5 text-[13px] leading-5 transition-colors duration-(--motion-fast) hover:bg-subtle pointer-coarse:min-h-11 [&::-webkit-details-marker]:hidden",
            COLS,
          )}
        >
          <JobStatusMark status={job.status} className="w-24 shrink-0 md:w-auto" />
          <span className="flex min-w-0 flex-1 items-baseline gap-2">
            <LayerValue layer="ui" className="shrink-0 font-medium">
              {label}
            </LayerValue>
            {Object.keys(job.args).length > 0 ? (
              <LayerValue layer="ui" className="truncate font-mono text-[12px] leading-4 text-muted-foreground">
                {argsText(job)}
              </LayerValue>
            ) : null}
          </span>
          <LayerValue
            layer="ui"
            className="order-last flex w-full min-w-0 items-center gap-1 pl-[1.125rem] text-[12px] leading-4 text-muted-foreground tabular-nums md:order-none md:block md:w-auto md:truncate md:pl-0 md:text-[13px] md:leading-5"
          >
            <span className="truncate">{costText(job)}</span>
            <span aria-hidden className="md:hidden">{copy.lab.header.sep}</span>
            <RelativeTime iso={job.createdAt} className="shrink-0 md:hidden" />
          </LayerValue>
          <span data-layer="ui" className="hidden text-muted-foreground tabular-nums md:block">
            <RelativeTime iso={job.createdAt} />
          </span>
          <ChevronRightIcon
            aria-hidden
            className="ml-auto size-4 shrink-0 text-muted-foreground transition-transform duration-(--motion-base) group-open:rotate-90 md:ml-0"
          />
        </summary>

        {/* The open row's left rule (ink, never a status colour); hidden with the rest while closed. */}
        <span aria-hidden className="pointer-events-none absolute inset-y-0 left-0 z-10 w-0.5 bg-foreground" />
        <div className="flex flex-col gap-3 border-t border-dashed border-line bg-canvas/60 px-3 py-3 group-open:animate-appear md:pl-[8.25rem]">
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[10px] tracking-wide text-muted-foreground uppercase">{copy.settings.queue.progress}</span>
            <Progress events={job.events} />
          </div>
          {job.refusal ? (
            <LayerValue as="p" layer="ui" className="text-[13px] leading-5">
              {fmt(copy.settings.queue.refusal, { reason: job.refusal })}
            </LayerValue>
          ) : null}
          {job.errorCode ? (
            <LayerValue as="p" layer="ui" className="font-mono text-[12px] leading-4 text-muted-foreground">
              {fmt(copy.settings.queue.code, { code: job.errorCode })}
            </LayerValue>
          ) : null}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] leading-4 text-muted-foreground">
            <LayerValue layer="ui" className="font-mono">
              {job.id}
            </LayerValue>
            <LayerValue layer="ui" className="font-mono md:hidden">
              {formatUtc(job.createdAt)}
            </LayerValue>
            {spec?.paid ? (
              <LayerValue layer="ui">
                {job.confirmedAt ? copy.settings.queue.confirmed : copy.settings.queue.waitingConfirm}
              </LayerValue>
            ) : null}
            {job.cancelRequested ? <LayerValue layer="ui">{copy.settings.queue.cancelRequested}</LayerValue> : null}
          </div>
          <JobActions
            id={job.id}
            label={label}
            estimateUsd={job.estimateUsd}
            needsConfirm={needsConfirm}
            canCancel={live && !job.cancelRequested}
          />
        </div>
      </details>
    </li>
  );
}
