"use client";

// Accept / Reject buttons for one suggested shape label (reel.accept / reel.reject, free jobs).
// Both buttons share one status line under the row, so a long result ("Fixtures mode: ...")
// never pushes the row sideways on a phone. A new result slides in (readout-in; instant under
// reduced motion); the live region itself stays mounted so screen readers hear each change.

import { useState } from "react";

import { JobButton } from "@/components/shared/job-button";
import type { ActionResult } from "@/lib/job-kinds";
import { cn } from "@/lib/utils";

type LabelActionsProps = {
  sc: string;
  /** The shape field as strategist.reel takes it: hook_shape, format, cta, beats, or all. */
  field: string;
  acceptLabel: string;
  /** Omit to show Accept only (reject takes one field at a time, never all). */
  rejectLabel?: string;
  className?: string;
};

export function LabelActions({ sc, field, acceptLabel, rejectLabel, className }: LabelActionsProps) {
  const [result, setResult] = useState<ActionResult | null>(null);
  return (
    <span className={cn("flex min-w-0 flex-col items-end gap-1", className)}>
      <span className="flex items-center gap-1.5 pointer-coarse:[&_button]:h-9">
        <JobButton kind="reel.accept" args={{ sc, field }} label={acceptLabel} size="xs" quiet onResult={setResult} />
        {rejectLabel ? (
          <JobButton kind="reel.reject" args={{ sc, field }} label={rejectLabel} size="xs" variant="ghost" quiet onResult={setResult} />
        ) : null}
      </span>
      <span role="status" aria-live="polite" data-layer="ui" className="max-w-72 text-right text-[11px] leading-4 text-muted-foreground empty:hidden">
        {result?.message ? (
          <span key={result.message} className="readout-in inline-block">
            {result.message}
          </span>
        ) : null}
      </span>
    </span>
  );
}
