// Settings → Jobs (D26): the runner (online / last seen, from the Upstash heartbeat), this month's
// spend against the caps, the queue with each job's status as a glyph and a word and its fixed
// progress lines, the limits the runner keeps, and the Pause switch. Round 3 (less text): no
// subtitle; labels, values and buttons stay, and every explanation sits behind one (i) (Stripe
// settings reference); the cards and rows fade in and the spend meters grow in once, all still
// under reduced motion. When the runner is not online, one dashed card shows the command that
// starts it on the laptop; the other ways to run it sit behind its (i).

import type { Metadata } from "next";
import { Suspense } from "react";

import { JobList, JobListHeader } from "@/components/settings/job-list";
import { RunnerCard, SpendCard } from "@/components/settings/overview-cards";
import { PauseSwitch } from "@/components/settings/pause-switch";
import { CopyCommand } from "@/components/shared/copy-command";
import { InfoHint } from "@/components/shared/info-hint";
import { LayerValue } from "@/components/shared/layer-value";
import { PageHeader } from "@/components/shared/page-header";
import { PageSkeleton } from "@/components/shared/page-skeleton";
import { copy, fmt } from "@/lib/copy";
import { getJobs, getRunnerStatus, getSpend, type JobRow, type RunnerStatus } from "@/lib/data";
import { formatUsd } from "@/lib/format";
import { JOB_LIMITS } from "@/lib/job-kinds";

export const metadata: Metadata = { title: copy.pages.jobs.title };

export default function JobsPage() {
  return (
    <div data-page="jobs" className="mx-auto w-full max-w-[1400px]">
      <Suspense
        fallback={
          <>
            <PageHeader title={copy.pages.jobs.title} />
            <PageSkeleton rows={8} />
          </>
        }
      >
        <JobsContent />
      </Suspense>
    </div>
  );
}

const UNKNOWN_RUNNER: RunnerStatus = { state: "unknown", lastSeen: null, paused: false };

async function JobsContent() {
  const [jobs, runner, spend] = await Promise.all([
    getJobs(),
    getRunnerStatus().catch(() => UNKNOWN_RUNNER),
    getSpend().catch(() => null),
  ]);
  const live = jobs.filter((j) => j.status === "queued" || j.status === "running");
  const recent = jobs.filter((j) => !live.includes(j));
  return (
    <>
      <PageHeader
        title={copy.pages.jobs.title}
        actions={
          <>
            {runner.state === "fixtures" ? <FixturesChip /> : null}
            <PauseSwitch paused={runner.paused} />
          </>
        }
      />

      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <RunnerCard status={runner} />
          <SpendCard service="modal" spend={spend} index={1} />
          <SpendCard service="apify" spend={spend} index={2} />
        </div>

        {/* On a phone the queue comes first, above the runner and spend cards. */}
        <section data-layer="ui" data-queue aria-labelledby="queue-title" className="flex flex-col gap-2 max-sm:order-first">
          <h2 id="queue-title" className="text-sm font-medium">
            {copy.settings.queue.title}
          </h2>
          {jobs.length ? (
            <div className="overflow-hidden rounded-xl border border-line bg-surface">
              <JobListHeader />
              <QueueGroup title={copy.settings.queue.live} jobs={live} empty={copy.settings.queue.liveEmpty} />
              {recent.length ? <QueueGroup title={copy.settings.queue.recent} jobs={recent} /> : null}
            </div>
          ) : (
            <QueueEmpty />
          )}
        </section>

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
          {runner.state !== "online" ? <RunnerSteps /> : null}
          <Limits />
        </div>
      </div>
    </>
  );
}

/** Fixtures mode as a small dashed chip; the full sentence sits behind its (i). */
function FixturesChip() {
  const r = copy.settings.runner;
  return (
    <span
      data-layer="ui"
      data-fixtures
      className="inline-flex h-7 items-center gap-1.5 rounded-full border border-dashed border-line pr-2 pl-2.5 text-[12px] leading-4 text-muted-foreground"
    >
      <span>{r.fixturesChip}</span>
      <InfoHint label={r.fixturesLabel} align="end">
        {r.fixtures}
      </InfoHint>
    </span>
  );
}

function QueueGroup({ title, jobs, empty }: { title: string; jobs: JobRow[]; empty?: string }) {
  return (
    <div className="border-b border-line last:border-b-0">
      <div className="flex h-8 items-center gap-2 border-b border-line bg-canvas/60 px-3">
        <span className="font-mono text-[10px] tracking-wide text-muted-foreground uppercase">{title}</span>
        <LayerValue
          layer="ui"
          className="inline-flex h-4 min-w-4 items-center justify-center rounded-full border border-line px-1 font-mono text-[10px] leading-none text-muted-foreground tabular-nums"
        >
          {jobs.length}
        </LayerValue>
      </div>
      {jobs.length ? <JobList jobs={jobs} /> : <p className="px-3 py-2.5 text-[13px] leading-5 text-muted-foreground">{empty}</p>}
    </div>
  );
}

/** No jobs at all: one short line; what fills the queue sits behind its (i). */
function QueueEmpty() {
  const q = copy.settings.queue;
  return (
    <div data-layer="ui" data-queue-empty className="flex items-center gap-1.5 rounded-xl border border-dashed border-line bg-surface px-4 py-3">
      <p className="text-[13px] leading-5 font-medium">{q.emptyTitle}</p>
      <InfoHint label={q.emptyLabel}>{q.emptyBody}</InfoHint>
    </div>
  );
}

/** The runner is not online: the one command that starts it. Why, and the other two ways to run
 *  it (once, or at logon), sit behind the (i), each with its own copyable command. */
function RunnerSteps() {
  const r = copy.settings.runner;
  const more = [
    { title: r.stepOnce, body: r.stepOnceBody, command: r.stepOnceCommand },
    { title: r.stepLogon, body: r.stepLogonBody, command: r.stepLogonCommand },
  ];
  return (
    <section data-layer="ui" data-runner-steps className="flex flex-col gap-3 rounded-xl border border-dashed border-line bg-surface p-4">
      <div className="flex items-center gap-1.5">
        <h2 className="text-[13px] leading-5 font-medium">{r.setupTitle}</h2>
        <InfoHint label={r.setupLabel} contentClassName="w-80">
          <div className="flex flex-col gap-3">
            <p>{r.setupBody}</p>
            <p className="text-muted-foreground">{r.stepStartBody}</p>
            {more.map((step) => (
              <div key={step.command} className="flex flex-col gap-1">
                <span className="font-medium">{step.title}</span>
                <span className="text-muted-foreground">{step.body}</span>
                <CopyCommand command={step.command} label={null} />
              </div>
            ))}
          </div>
        </InfoHint>
      </div>
      <CopyCommand command={r.stepStartCommand} label={null} />
    </section>
  );
}

function Limits() {
  const l = copy.settings.limits;
  const rows: Array<[string, string]> = [
    [l.paidRunning, String(JOB_LIMITS.paid_running_max)],
    [l.paidUsdDay, fmt(l.usd, { usd: formatUsd(JOB_LIMITS.paid_usd_per_day) })],
    [l.paidJobsDay, String(JOB_LIMITS.paid_jobs_per_day)],
    [l.tribeMonth, String(JOB_LIMITS.tribe_reads_per_month)],
    [l.confirmExpires, fmt(l.minutes, { n: JOB_LIMITS.confirm_expires_min })],
  ];
  return (
    <section data-layer="ui" className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-4">
      <div className="flex items-center gap-1.5">
        <h2 className="text-[13px] leading-5 font-medium">{l.title}</h2>
        <InfoHint label={l.hintLabel}>{l.body}</InfoHint>
      </div>
      <dl className="flex flex-col divide-y divide-line">
        {rows.map(([k, v]) => (
          <div key={k} data-row className="flex h-9 items-center justify-between gap-3 pointer-coarse:h-11">
            <dt className="text-[13px] leading-5 text-muted-foreground">{k}</dt>
            <dd>
              <LayerValue layer="ui" className="font-mono text-[12px] leading-4 font-medium tabular-nums">
                {v}
              </LayerValue>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
