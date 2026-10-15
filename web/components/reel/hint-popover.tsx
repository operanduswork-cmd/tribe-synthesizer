"use client";

// A popover on any small trigger, opened the way the (i) hints open (components/shared/info-hint):
// a mouse opens it by hovering (a click pins it open), a finger or the keyboard by pressing, so it
// works on touch. Used where a picture stands in for words (round 3, D30): legend swatches whose
// names show on hover or tap, and the lock button that holds the laptop commands. The trigger
// keeps a 44px hit area on touch (tap-target). Popover content is only in the page while open.

import { useEffect, useRef, useState, type MouseEvent, type PointerEvent, type ReactNode } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Layer } from "@/lib/contract";
import { cn } from "@/lib/utils";

const OPEN_DELAY_MS = 120;
const CLOSE_DELAY_MS = 160;

type HintPopoverProps = {
  /** What the trigger shows (an icon or a swatch); decorative, the label names it. */
  trigger: ReactNode;
  /** The trigger's accessible name, from copy. */
  label: string;
  children: ReactNode;
  /** Whose text the popover holds: data-layer on its content. Default "ui". */
  layer?: Layer;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  className?: string;
  contentClassName?: string;
  /** Extra data attributes on the content, e.g. { "data-swatch-name": "" }. */
  contentData?: Record<`data-${string}`, string>;
  /** Extra data attributes on the trigger. */
  triggerData?: Record<`data-${string}`, string>;
};

export function HintPopover({
  trigger,
  label,
  children,
  layer = "ui",
  side = "top",
  align = "center",
  className,
  contentClassName,
  contentData,
  triggerData,
}: HintPopoverProps) {
  const [open, setOpen] = useState(false);
  const via = useRef<"hover" | "press" | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const clear = () => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);

  function hoverIn(e: PointerEvent) {
    if (e.pointerType !== "mouse") return;
    clear();
    if (open) return;
    timer.current = window.setTimeout(() => {
      via.current = "hover";
      setOpen(true);
    }, OPEN_DELAY_MS);
  }
  function hoverOut(e: PointerEvent) {
    if (e.pointerType !== "mouse") return;
    clear();
    if (!open || via.current !== "hover") return;
    timer.current = window.setTimeout(() => setOpen(false), CLOSE_DELAY_MS);
  }
  function onOpenChange(next: boolean) {
    clear();
    if (next) via.current = "press";
    setOpen(next);
  }
  function onClick(e: MouseEvent) {
    if (open && via.current === "hover") {
      e.preventDefault();
      clear();
      via.current = "press";
    }
  }

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger
        aria-label={label}
        onPointerEnter={hoverIn}
        onPointerLeave={hoverOut}
        onClick={onClick}
        className={cn(
          "tap-target inline-flex shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground data-[state=open]:text-foreground",
          className,
        )}
        {...triggerData}
      >
        {trigger}
      </PopoverTrigger>
      <PopoverContent
        data-layer={layer}
        side={side}
        align={align}
        collisionPadding={16}
        onPointerEnter={(e) => e.pointerType === "mouse" && clear()}
        onPointerLeave={hoverOut}
        onOpenAutoFocus={(e) => via.current === "hover" && e.preventDefault()}
        onCloseAutoFocus={(e) => via.current === "hover" && e.preventDefault()}
        className={cn("max-w-[calc(100vw-2rem)] text-ui text-foreground", contentClassName)}
        {...contentData}
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}

export type Swatch = { key: string; name: string; mark: ReactNode };

/** A legend as swatches only (round 3): each swatch is a small button whose name shows on hover
 *  or tap, and is its accessible name. */
export function SwatchLegend({ label, items, className }: { label: string; items: Swatch[]; className?: string }) {
  return (
    <ul aria-label={label} data-layer="ui" data-swatches="" className={cn("flex flex-wrap items-center gap-x-1 gap-y-1", className)}>
      {items.map((s) => (
        <li key={s.key} className="inline-flex">
          <HintPopover
            label={s.name}
            trigger={s.mark}
            className="h-6 min-w-6 px-1"
            contentClassName="w-auto px-2 py-1 text-[11px] leading-4"
            contentData={{ "data-swatch-name": s.key }}
            triggerData={{ "data-swatch": s.key }}
          >
            {s.name}
          </HintPopover>
        </li>
      ))}
    </ul>
  );
}
