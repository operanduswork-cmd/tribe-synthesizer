"use client";

// The confirm step for a paid job (D26). The job row already exists, unconfirmed, with its
// estimate; "Confirm" sets confirmed_at (that click is his go for this one job at this estimate)
// and "Not now" asks for it to be cancelled. The runner re-checks caps, limits and expiry.

import { useTransition } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { copy, fmt } from "@/lib/copy";
import { formatUsd } from "@/lib/format";
import { JOB_LIMITS, type ActionResult } from "@/lib/job-kinds";
import { cancelJob, confirmJob } from "@/lib/jobs";

type ConfirmJobDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The unconfirmed job's id, from enqueueJob. */
  jobId: string;
  /** What the job does, from copy (e.g. "TRIBE deep read of DEMO0000001"). */
  label: string;
  /** The estimate stored on the job row. */
  estimateUsd: number;
  onDone?: (result: ActionResult) => void;
};

export function ConfirmJobDialog({ open, onOpenChange, jobId, label, estimateUsd, onDone }: ConfirmJobDialogProps) {
  const [pending, start] = useTransition();
  const usd = formatUsd(estimateUsd);

  function finish(action: (id: string) => Promise<ActionResult>) {
    start(async () => {
      const result = await action(jobId);
      onDone?.(result);
      onOpenChange(false);
    });
  }

  return (
    <AlertDialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <AlertDialogContent data-layer="ui">
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.jobs.confirm.title}</AlertDialogTitle>
          <AlertDialogDescription>{fmt(copy.jobs.confirm.body, { label, usd })}</AlertDialogDescription>
        </AlertDialogHeader>
        <p className="text-ui text-muted-foreground">{copy.jobs.confirm.limits}</p>
        <p className="text-ui text-muted-foreground">{fmt(copy.jobs.confirm.expires, { min: JOB_LIMITS.confirm_expires_min })}</p>
        <AlertDialogFooter>
          <AlertDialogCancel
            disabled={pending}
            onClick={(e) => {
              e.preventDefault();
              finish(cancelJob);
            }}
          >
            {copy.jobs.confirm.cancel}
          </AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            onClick={(e) => {
              e.preventDefault();
              finish(confirmJob);
            }}
          >
            {pending ? copy.jobs.working : fmt(copy.jobs.confirm.go, { usd })}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
