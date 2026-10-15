"use client";

// The buttons on one job row: Confirm for a paid job still waiting for its go (opens the confirm
// dialog with the stored estimate; that click is the go for this one job, D26) and Cancel for a
// live job (the runner stops at its next safe point). In fixtures mode both say so and change
// nothing.

import { useState, useTransition } from "react";

import { ConfirmJobDialog } from "@/components/shared/confirm-job-dialog";
import { Button } from "@/components/ui/button";
import { copy } from "@/lib/copy";
import { cancelJob } from "@/lib/jobs";

type JobActionsProps = {
  id: string;
  /** What the job does (copy.jobKinds), for the confirm dialog. */
  label: string;
  estimateUsd: number;
  needsConfirm: boolean;
  canCancel: boolean;
};

export function JobActions({ id, label, estimateUsd, needsConfirm, canCancel }: JobActionsProps) {
  const [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState("");
  const [pending, start] = useTransition();

  if (!needsConfirm && !canCancel) return null;

  function onCancel() {
    start(async () => {
      const r = await cancelJob(id);
      setMessage(r.message);
    });
  }

  return (
    <div data-layer="ui" className="flex flex-wrap items-center gap-2">
      {needsConfirm ? (
        <Button type="button" size="xs" onClick={() => setConfirm(true)} disabled={pending}>
          {copy.settings.queue.confirm}
        </Button>
      ) : null}
      {canCancel ? (
        <Button type="button" size="xs" variant="outline" onClick={onCancel} disabled={pending} aria-busy={pending}>
          {pending ? copy.jobs.working : copy.settings.queue.cancel}
        </Button>
      ) : null}
      <span role="status" aria-live="polite" className="text-[13px] leading-5 text-muted-foreground">
        {message}
      </span>
      {confirm ? (
        <ConfirmJobDialog
          open
          onOpenChange={(open) => !open && setConfirm(false)}
          jobId={id}
          label={label}
          estimateUsd={estimateUsd}
          onDone={(r) => setMessage(r.message)}
        />
      ) : null}
    </div>
  );
}
