"use client";

// A laptop command in a mono block with a copy button (Stripe / Vercel onboarding reference).
// Used where private details stay on the laptop, e.g. `python -m strategist.render reel <sc> --open`.
// The command wraps (at spaces first) instead of scrolling sideways, so a flag at the end of a
// long command is never cut off on a phone.

import { CheckIcon, CopyIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

type CopyCommandProps = {
  command: string;
  /** A short label above the block (from copy). Defaults to "Run on the laptop". */
  label?: string | null;
  className?: string;
};

export function CopyCommand({ command, label = copy.copyCommand.label, className }: CopyCommandProps) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(command);
      setState("copied");
    } catch {
      setState("failed");
    }
    window.setTimeout(() => setState("idle"), 1600);
  }

  return (
    <div data-layer="ui" className={cn("flex flex-col gap-1", className)}>
      {label ? <span className="text-ui text-muted-foreground">{label}</span> : null}
      <div className="flex min-h-9 items-center gap-2 rounded-md border border-line bg-subtle pl-3 pr-1">
        <code className="min-w-0 flex-1 py-2 font-mono text-mono whitespace-pre-wrap wrap-anywhere">{command}</code>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={onCopy}
          aria-label={copy.copyCommand.copy}
          title={state === "failed" ? copy.copyCommand.failed : copy.copyCommand.copy}
        >
          {state === "copied" ? <CheckIcon /> : <CopyIcon />}
        </Button>
      </div>
      <span role="status" aria-live="polite" className="sr-only">
        {state === "copied" ? copy.copyCommand.copied : state === "failed" ? copy.copyCommand.failed : ""}
      </span>
    </div>
  );
}
