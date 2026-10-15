"use client";

// The fold under the board for "Creators and baselines": one header row (the whole row is the
// toggle, through the button's ::after, as on the board cards) with the (i) hint right after the
// title (Plain reporting: an (i) next to the title instead of a line of text), then the content,
// which fades in when opened. Not a <details>: the hint is a button, and a button inside a
// <summary> would be a control inside a control. Closed content stays in the DOM, hidden, as in a
// closed <details>.

import { ChevronRightIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { InfoHint } from "@/components/shared/info-hint";
import { LayerTag } from "@/components/shared/layer-tag";
import { cn } from "@/lib/utils";

export function CreatorsDisclosure({
  title,
  hint,
  hintLabel,
  children,
}: {
  title: string;
  hint: ReactNode;
  hintLabel: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <section data-board="creators" data-open={open ? "" : undefined} className="rounded-xl border border-line bg-surface">
      <div
        data-layer="ui"
        className={cn(
          "relative flex h-10 items-center gap-2 rounded-xl px-3 text-ui font-medium transition-[background-color] duration-(--motion-fast) ease-(--motion-ease) hover:bg-subtle pointer-coarse:h-11",
          open && "rounded-b-none",
        )}
      >
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          data-board="creators-toggle"
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "flex min-w-0 items-center gap-2 text-left outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:outline-2 focus-visible:after:outline-indigo-accent",
            open && "after:rounded-b-none",
          )}
        >
          <ChevronRightIcon
            aria-hidden
            className={cn("size-4 shrink-0 text-muted-foreground transition-transform duration-(--motion-base) ease-(--motion-ease)", open && "rotate-90")}
          />
          <span className="truncate">{title}</span>
          <LayerTag layer="counts" />
        </button>
        <InfoHint label={hintLabel} side="top" align="start" className="relative z-10">
          {hint}
        </InfoHint>
      </div>
      <div id={id} hidden={!open} className="animate-appear border-t border-line">
        <div className="flex flex-col gap-4 px-4 py-4">{children}</div>
      </div>
    </section>
  );
}
