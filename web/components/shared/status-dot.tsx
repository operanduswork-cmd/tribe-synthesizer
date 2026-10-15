// A status dot and its word ("● online", "○ queued"). Status is told by the dot's form and the
// word, never by red or green fills: solid = up or done, pulse = working, hollow = waiting or
// off, dashed = stopped or refused, muted = cancelled or unknown.

import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

export type DotTone = "solid" | "pulse" | "hollow" | "dashed" | "muted";

const DOT: Record<DotTone, string> = {
  solid: "bg-foreground",
  pulse: "bg-foreground animate-pulse",
  hollow: "border border-foreground bg-transparent",
  dashed: "border border-dashed border-foreground bg-transparent",
  muted: "bg-muted-foreground/40",
};

type StatusDotProps = {
  tone: DotTone;
  /** The word shown after the dot (from copy). */
  label: string;
  /** Optional muted detail after the word, e.g. "last seen 3 min ago". */
  detail?: string | null;
  className?: string;
};

export function StatusDot({ tone, label, detail, className }: StatusDotProps) {
  return (
    <span data-layer="ui" data-tone={tone} className={cn("inline-flex items-center gap-1.5 text-ui", className)}>
      <span aria-hidden className={cn("size-2 shrink-0 rounded-full", DOT[tone])} />
      <span>{label}</span>
      {detail ? <span className="text-muted-foreground">{detail}</span> : null}
    </span>
  );
}

export type JobStatusName = keyof typeof copy.status;

export const JOB_STATUS_TONE: Record<JobStatusName, DotTone> = {
  queued: "hollow",
  running: "pulse",
  done: "solid",
  failed: "dashed",
  interrupted: "dashed",
  refused: "dashed",
  cancelled: "muted",
};

/** A job's status as a dot and its word. */
export function JobStatusDot({ status, className }: { status: JobStatusName; className?: string }) {
  return <StatusDot tone={JOB_STATUS_TONE[status]} label={copy.status[status]} className={className} />;
}
