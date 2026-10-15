"use client";

// A small (i) that opens an explanation (Plain reporting reference: an (i) on every chart title).
// A Radix Popover, not a Tooltip, because a tooltip never opens on touch: a mouse opens it by
// hovering (and a click pins it open), a finger or the keyboard by pressing. The trigger is a 16px
// icon with a 44px hit area on touch (tap-target). The content carries data-layer, so the wall
// checks see whose text it is. Never put it inside a heading whose text a test matches exactly:
// put it next to the heading.

import { InfoIcon } from "lucide-react";
import { useEffect, useRef, useState, type MouseEvent, type PointerEvent, type ReactNode } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { copy } from "@/lib/copy";
import type { Layer } from "@/lib/contract";
import { cn } from "@/lib/utils";

const OPEN_DELAY_MS = 120;
const CLOSE_DELAY_MS = 160;

export type InfoHintProps = {
  /** The hint text, from copy/en.json. */
  children: ReactNode;
  /** The trigger's accessible name (from copy), e.g. fmt(copy.ui.hintAbout, { topic }). Default copy.ui.hint. */
  label?: string;
  /** Whose text the hint is: data-layer on the popover content. Default "ui". */
  layer?: Layer;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  /** Classes for the trigger button. */
  className?: string;
  /** Classes for the popover content. */
  contentClassName?: string;
};

export function InfoHint({ children, label, layer = "ui", side = "top", align = "center", className, contentClassName }: InfoHintProps) {
  const [open, setOpen] = useState(false);
  // How the open hint was opened: a hover closes again on leave, a press stays until dismissed.
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
  // A click on a hint the mouse opened pins it open instead of closing it.
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
        aria-label={label ?? copy.ui.hint}
        data-hint-trigger=""
        onPointerEnter={hoverIn}
        onPointerLeave={hoverOut}
        onClick={onClick}
        className={cn(
          "tap-target inline-flex size-4 shrink-0 items-center justify-center rounded-full align-[-0.125em] text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground data-[state=open]:text-foreground",
          className,
        )}
      >
        <InfoIcon aria-hidden className="size-4" />
      </PopoverTrigger>
      <PopoverContent
        data-layer={layer}
        data-hint=""
        side={side}
        align={align}
        collisionPadding={16}
        onPointerEnter={(e) => e.pointerType === "mouse" && clear()}
        onPointerLeave={hoverOut}
        onOpenAutoFocus={(e) => via.current === "hover" && e.preventDefault()}
        onCloseAutoFocus={(e) => via.current === "hover" && e.preventDefault()}
        className={cn("w-72 max-w-[calc(100vw-2rem)] text-ui text-foreground", contentClassName)}
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
