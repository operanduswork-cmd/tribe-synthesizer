// A shape label (hook shape, beat, CTA, format). Outlined in the accent while Claude only
// suggested it, filled once accepted (or measured from the caption or post data, with its own
// hint), struck through when rejected. The actions slot takes Accept / Reject buttons (JobButton
// with reel.accept / reel.reject).

import type { ReactNode } from "react";

import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

export type ShapeStatus = "suggested" | "accepted" | "rejected";

type ShapeChipProps = {
  label: string;
  status: ShapeStatus;
  /** Shown before the label in mono, e.g. "hook" or "beat 2". */
  field?: string;
  actions?: ReactNode;
  className?: string;
  /** The hover text. Defaults to the hint, so a table cell can pass the full label when the chip cuts it off. */
  title?: string;
  /** Replaces the status hint (hover and screen reader), e.g. for a label measured from post data. */
  hint?: string;
};

const HINT: Record<ShapeStatus, string> = {
  suggested: copy.shape.suggestedHint,
  accepted: copy.shape.acceptedHint,
  rejected: copy.shape.rejected,
};

// The screen-reader status is the short status word (D30, less text); the full hint stays on hover.
const SHORT: Record<ShapeStatus, string> = {
  suggested: copy.shape.suggested,
  accepted: copy.shape.accepted,
  rejected: copy.shape.rejected,
};

export function ShapeChip({ label, status, field, actions, className, title, hint }: ShapeChipProps) {
  const statusHint = hint ?? SHORT[status];
  return (
    <span
      data-layer="shape"
      data-status={status}
      title={title ?? hint ?? HINT[status]}
      className={cn(
        "inline-flex h-6 max-w-full items-center gap-1.5 rounded-md border px-2 text-ui",
        status === "suggested" && "border-indigo-accent bg-transparent text-indigo-accent",
        status === "accepted" && "border-line bg-subtle text-foreground",
        status === "rejected" && "border-dashed border-line text-muted-foreground line-through",
        className,
      )}
    >
      {field ? <span className="font-mono text-mono opacity-70">{field}</span> : null}
      <span className="truncate">{label}</span>
      <span className="sr-only">{statusHint}</span>
      {actions}
    </span>
  );
}
