// An empty or first-run state. Copilot style: what appears and when, with an optional
// progress count ("3/10"); Stripe / Vercel onboarding style: numbered steps with copyable
// laptop commands. No upsell rows, no big black call to action.

import type { ReactNode } from "react";

import { CopyCommand } from "@/components/shared/copy-command";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

export type EmptyStep = { title: string; body?: string; command?: string };

type EmptyStateProps = {
  title: string;
  body?: string;
  icon?: ReactNode;
  /** e.g. { done: 3, total: 10 } for "Patterns compare groups once 10 reels are in". */
  progress?: { done: number; total: number };
  steps?: EmptyStep[];
  action?: ReactNode;
  className?: string;
};

export function EmptyState({ title, body, icon, progress, steps, action, className }: EmptyStateProps) {
  const pct = progress ? Math.min(100, Math.round((progress.done / Math.max(1, progress.total)) * 100)) : 0;
  return (
    <section data-layer="ui" className={cn("flex flex-col gap-4 rounded-xl border border-dashed border-line bg-surface p-6", className)}>
      <div className="flex items-start gap-3">
        {icon ? <span className="mt-0.5 text-muted-foreground [&_svg]:size-4">{icon}</span> : null}
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="text-sm font-medium">{title}</h2>
          {body ? <p className="text-ui text-muted-foreground">{body}</p> : null}
        </div>
      </div>
      {progress ? (
        <div className="flex items-center gap-3">
          <div
            className="h-1 w-40 overflow-hidden rounded-full bg-subtle"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.done}
          >
            <div className="h-full bg-foreground" style={{ width: `${pct}%` }} />
          </div>
          <span className="font-mono text-mono tabular-nums text-muted-foreground">
            {fmt(copy.empty.progress, { done: progress.done, total: progress.total })}
          </span>
        </div>
      ) : null}
      {steps?.length ? (
        <ol className="flex flex-col gap-3">
          {steps.map((step, i) => (
            <li key={i} className="flex gap-3">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full border border-line font-mono text-[10px] tabular-nums">
                {i + 1}
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="text-ui font-medium">{step.title}</span>
                {step.body ? <span className="text-ui text-muted-foreground">{step.body}</span> : null}
                {step.command ? <CopyCommand command={step.command} label={null} /> : null}
              </div>
            </li>
          ))}
        </ol>
      ) : null}
      {action ? <div>{action}</div> : null}
    </section>
  );
}
