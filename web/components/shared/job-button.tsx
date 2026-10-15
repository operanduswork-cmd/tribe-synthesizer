"use client";

// A run button for one job kind from contracts/job-kinds.json (D26). Disabled kinds render
// disabled with their stage. Free kinds queue on click; paid kinds queue unconfirmed and open
// ConfirmJobDialog with the estimate. The result message (fixtures mode, queued, duplicate...)
// shows next to the button.

import { useState, useTransition, type ReactNode } from "react";

import { ConfirmJobDialog } from "@/components/shared/confirm-job-dialog";
import { Button } from "@/components/ui/button";
import { copy, fmt } from "@/lib/copy";
import { formatUsd } from "@/lib/format";
import { jobSpec, type ActionResult, type JobKind } from "@/lib/job-kinds";
import { enqueueJob } from "@/lib/jobs";
import { cn } from "@/lib/utils";

type JobButtonProps = {
  kind: JobKind;
  args?: Record<string, string>;
  /** The button text, from copy. */
  label: string;
  /** What the job does, for the confirm dialog (from copy). Defaults to label. */
  confirmLabel?: string;
  icon?: ReactNode;
  variant?: "default" | "outline" | "secondary" | "ghost";
  size?: "default" | "sm" | "xs" | "lg";
  /** Show "about $0.10" after a paid button. Default true. */
  showEstimate?: boolean;
  /** Hide the inline result message (use onResult instead). */
  quiet?: boolean;
  className?: string;
  onResult?: (result: ActionResult) => void;
};

export function JobButton({
  kind,
  args = {},
  label,
  confirmLabel,
  icon,
  variant = "outline",
  size = "sm",
  showEstimate = true,
  quiet = false,
  className,
  onResult,
}: JobButtonProps) {
  const spec = jobSpec(kind);
  const [pending, start] = useTransition();
  const [result, setResult] = useState<ActionResult | null>(null);
  const [confirm, setConfirm] = useState<{ jobId: string; estimateUsd: number } | null>(null);

  function report(r: ActionResult) {
    setResult(r);
    onResult?.(r);
  }

  const estimate =
    spec?.paid && showEstimate ? (
      <span data-estimate className="font-mono text-mono text-muted-foreground">
        {fmt(copy.jobs.estimate, { usd: formatUsd(spec.estimate_usd) })}
      </span>
    ) : null;

  // A disabled paid kind still shows what it will cost once its stage is on (D26: every paid
  // button shows its estimate).
  if (!spec || !spec.enabled) {
    const stage = spec?.stage ?? 0;
    return (
      <span data-layer="ui" data-job-kind={kind} data-stage={stage} className={cn("inline-flex flex-wrap items-center gap-x-2 gap-y-1", className)}>
        <Button type="button" variant={variant} size={size} disabled title={fmt(copy.jobs.disabled, { stage })}>
          {icon}
          {label}
        </Button>
        {estimate}
        <span className="font-mono text-mono text-muted-foreground">{fmt(copy.jobs.stage, { stage })}</span>
      </span>
    );
  }

  function onClick() {
    start(async () => {
      const r = await enqueueJob(kind, args);
      if (r.ok && r.needsConfirm && r.jobId) {
        setResult(null);
        setConfirm({ jobId: r.jobId, estimateUsd: r.needsConfirm.estimateUsd });
        return;
      }
      report(r);
    });
  }

  return (
    <span data-layer="ui" data-job-kind={kind} className={cn("inline-flex flex-wrap items-center gap-2", className)}>
      <Button type="button" variant={variant} size={size} onClick={onClick} disabled={pending} aria-busy={pending}>
        {icon}
        {pending ? copy.jobs.working : label}
      </Button>
      {estimate}
      {!quiet ? (
        <span role="status" aria-live="polite" className="text-ui text-muted-foreground">
          {result?.message ?? ""}
        </span>
      ) : null}
      {confirm ? (
        <ConfirmJobDialog
          open
          onOpenChange={(open) => !open && setConfirm(null)}
          jobId={confirm.jobId}
          label={confirmLabel ?? label}
          estimateUsd={confirm.estimateUsd}
          onDone={report}
        />
      ) : null}
    </span>
  );
}
