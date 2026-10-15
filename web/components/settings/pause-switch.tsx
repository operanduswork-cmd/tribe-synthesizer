"use client";

// The Pause switch (D26), Stripe settings style: a short label, an (i) with what pausing does,
// and the switch. On: the runner leaves queued jobs alone until it is off again; a job already
// running finishes. While on, the glyph turns into the runner's paused mark (bars in a ring)
// and the frame goes dashed, so the state shows without colour. The switch moves only when
// the site saved it (setPaused); in fixtures mode it stays put and says why. Until the page
// hydrates, Radix renders a 13px see-through checkbox beside the switch for forms (pointer
// events off, never tapped, and there is no form here); the row hides it so it never reads as
// a small tap target.

import { PauseIcon } from "lucide-react";
import { useId, useState, useTransition } from "react";

import { StatusGlyph } from "@/components/settings/status-mark";
import { InfoHint } from "@/components/shared/info-hint";
import { Switch } from "@/components/ui/switch";
import { copy } from "@/lib/copy";
import { setPaused } from "@/lib/jobs";
import { cn } from "@/lib/utils";

export function PauseSwitch({ paused, className }: { paused: boolean; className?: string }) {
  const id = useId();
  const [on, setOn] = useState(paused);
  const [message, setMessage] = useState("");
  const [pending, start] = useTransition();
  const p = copy.settings.pause;

  function toggle(next: boolean) {
    start(async () => {
      const r = await setPaused(next);
      setMessage(r.message);
      if (r.ok) setOn(next);
    });
  }

  return (
    <div data-layer="ui" data-pause={on ? "on" : "off"} className={cn("flex w-full flex-col gap-1 sm:w-auto", className)}>
      <div
        className={cn(
          "flex min-h-11 items-center gap-2 rounded-lg border bg-surface py-1.5 pr-3 pl-3 transition-colors duration-(--motion-base) [&>input[aria-hidden]]:hidden",
          on ? "border-dashed border-foreground/50" : "border-line",
        )}
      >
        <label htmlFor={id} className="flex cursor-pointer items-center gap-2 text-[13px] leading-5 font-medium select-none">
          <span aria-hidden className={cn("flex size-4 items-center justify-center", on ? "text-foreground" : "text-muted-foreground")}>
            {on ? <StatusGlyph glyph="pause" className="size-3.5 animate-appear" /> : <PauseIcon className="size-3.5 animate-appear" />}
          </span>
          {p.label}
        </label>
        <InfoHint label={p.hintLabel} align="end">
          {p.body}
        </InfoHint>
        <span id={`${id}-body`} className="sr-only">
          {p.body}
        </span>
        <Switch
          id={id}
          checked={on}
          onCheckedChange={toggle}
          disabled={pending}
          aria-describedby={`${id}-body`}
          className="ml-auto sm:ml-4"
        />
      </div>
      <p role="status" aria-live="polite" className="text-[12px] leading-4 text-muted-foreground empty:hidden">
        {message}
      </p>
    </div>
  );
}
