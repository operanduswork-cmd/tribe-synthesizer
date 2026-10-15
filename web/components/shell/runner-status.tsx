// "Runner ● online" in the top bar (Vercel "● Ready" reference). Offline shows when it was last
// seen; jobs wait in the queue while it is off.

import { RelativeTime } from "@/components/shared/relative-time";
import { StatusDot, type DotTone } from "@/components/shared/status-dot";
import { copy } from "@/lib/copy";
import { getRunnerStatus, type RunnerState } from "@/lib/data";
import { cn } from "@/lib/utils";

const TONE: Record<RunnerState, DotTone> = { online: "solid", offline: "hollow", unknown: "muted", fixtures: "muted" };

export async function RunnerStatus({ compact = false, className }: { compact?: boolean; className?: string }) {
  const status = await getRunnerStatus().catch(() => ({ state: "unknown" as const, lastSeen: null, paused: false }));
  const tone: DotTone = status.paused ? "dashed" : TONE[status.state];
  const word = status.paused ? copy.runner.paused : copy.runner[status.state];
  // Compact (phone): the dot and its word without the "Runner" label; status is never a bare dot.
  return (
    <span
      data-layer="ui"
      data-runner-status={status.paused ? "paused" : status.state}
      title={copy.runner.help}
      className={cn("inline-flex items-center gap-2 text-ui", className)}
    >
      {compact ? <span className="sr-only">{copy.runner.label}</span> : <span className="text-muted-foreground">{copy.runner.label}</span>}
      <StatusDot tone={tone} label={word} className={compact ? "text-muted-foreground" : undefined} />
      {!compact && status.state === "offline" && status.lastSeen ? (
        <RelativeTime iso={status.lastSeen} className="hidden text-muted-foreground lg:inline" />
      ) : null}
    </span>
  );
}
