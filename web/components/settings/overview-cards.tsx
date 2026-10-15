// The three cards on top of Jobs (Vercel overview / usage references): the runner as its glyph
// and word with when it was last seen, then this month's spend for Modal and Apify as a big number
// with its cap beside it and a meter that grows in once. Where each number comes from, when it
// was read and Apify's free-credit note sit behind one (i) (round 3, less text). Money is ui
// text: never a count, never a brain value, never drawn in a layer colour.

import type { ReactNode } from "react";

import { runnerMark, StatusMark } from "@/components/settings/status-mark";
import { InfoHint } from "@/components/shared/info-hint";
import { LayerValue } from "@/components/shared/layer-value";
import { RelativeTime } from "@/components/shared/relative-time";
import { Rich } from "@/components/shared/rich";
import { copy, fmt } from "@/lib/copy";
import type { RunnerStatus } from "@/lib/data";
import { formatUsd } from "@/lib/format";
import type { SpendPage } from "@/lib/hosted";
import { cn } from "@/lib/utils";

type CardProps = {
  title: string;
  /** An (i) next to the title for the longer explanation. */
  hint?: ReactNode;
  aside?: ReactNode;
  /** Place in the row, for the staggered fade-in. */
  index?: number;
  children: ReactNode;
  className?: string;
};

function Card({ title, hint, aside, index = 0, children, className }: CardProps) {
  return (
    <section
      data-layer="ui"
      className={cn("flex min-w-0 animate-appear flex-col gap-3 sleek-card rounded-xl p-4", className)}
      style={{ animationDelay: `calc(${index} * var(--motion-stagger))` }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <h2 className="text-[13px] leading-5 font-medium">{title}</h2>
          {hint}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function RunnerCard({ status }: { status: RunnerStatus }) {
  const mark = runnerMark(status);
  const help = status.state !== "online" || status.paused;
  return (
    <Card
      title={copy.settings.runner.title}
      hint={help ? <InfoHint label={copy.settings.runner.helpLabel}>{copy.runner.help}</InfoHint> : null}
    >
      <div data-runner={status.state} className="flex flex-col gap-1">
        <StatusMark
          glyph={mark.glyph}
          tone={mark.tone}
          label={mark.word}
          glyphClassName="size-3.5"
          className="gap-2 text-base leading-6 font-medium"
        />
        <span className="text-[13px] leading-5 text-muted-foreground">
          {status.lastSeen ? (
            <Rich template={copy.runner.lastSeen} parts={{ when: <RelativeTime iso={status.lastSeen} className="tabular-nums" /> }} />
          ) : (
            <span>{copy.runner.never}</span>
          )}
        </span>
      </div>
    </Card>
  );
}

/** Spend against its cap as a thin meter: ink on the track's lighter step, quarter marks cut in
 *  as 2px surface gaps, growing in once (.grow-x, never on an element a test measures). Unread
 *  spend shows an empty dashed track. */
function SpendMeter({ label, used, cap }: { label: string; used: number | null; cap: number }) {
  const known = used !== null;
  const pct = known ? Math.min(100, Math.max(0, (used / Math.max(cap, 0.01)) * 100)) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={cap}
      aria-valuenow={known ? used : undefined}
      data-meter={known ? "read" : "unread"}
      className={cn("relative h-2 overflow-hidden rounded-full", known ? "bg-subtle" : "border border-dashed border-line")}
    >
      {known && pct > 0 ? (
        <div className="grow-x h-full rounded-full bg-foreground" style={{ width: `${Math.max(pct, 1.5)}%` }} />
      ) : null}
      {known
        ? [25, 50, 75].map((q) => (
            <span key={q} aria-hidden className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-surface" style={{ left: `${q}%` }} />
          ))
        : null}
    </div>
  );
}

export function SpendCard({ service, spend, index }: { service: "modal" | "apify"; spend: SpendPage | null; index?: number }) {
  const s = copy.settings.spend;
  const name = service === "modal" ? s.modal : s.apify;
  const raw = service === "modal" ? spend?.modal_usd : spend?.apify_usd;
  const used = typeof raw === "number" ? raw : null;
  const cap = service === "modal" ? (spend?.modal_cap_usd ?? 30) : (spend?.apify_cap_usd ?? 4.5);
  return (
    <Card
      index={index}
      title={name}
      hint={
        <InfoHint label={fmt(s.sourceLabel, { service: name })}>
          <span className="flex flex-col gap-1">
            <span>{service === "modal" ? s.modalSource : s.apifySource}</span>
            {service === "apify" ? <span>{fmt(s.apifyCap, { cap: formatUsd(cap) })}</span> : null}
            {spend?.as_of ? (
              <span data-as-of className="text-muted-foreground">
                <Rich template={s.asOf} parts={{ when: <RelativeTime iso={spend.as_of} /> }} />
              </span>
            ) : null}
          </span>
        </InfoHint>
      }
      aside={
        spend ? (
          <LayerValue layer="ui" className="font-mono text-[12px] leading-4 text-muted-foreground">
            {spend.month}
          </LayerValue>
        ) : null
      }
    >
      <div data-spend={service} className="flex flex-col gap-2.5">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          {used !== null ? (
            <LayerValue layer="ui" className="text-2xl font-semibold tracking-tight">
              {fmt(s.usd, { usd: used.toFixed(2) })}
            </LayerValue>
          ) : (
            <LayerValue layer="ui" className="text-base font-medium text-muted-foreground">
              {s.notRead}
            </LayerValue>
          )}
          <LayerValue layer="ui" className="text-[13px] leading-5 text-muted-foreground tabular-nums">
            {fmt(s.ofCap, { cap: formatUsd(cap) })}
          </LayerValue>
        </div>
        <SpendMeter label={name} used={used} cap={cap} />
      </div>
    </Card>
  );
}
