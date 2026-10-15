"use client";

// "All | Measured or accepted | Claude suggested" (mymind "Your tags | AI tags" reference; the
// raised segment on a grey track is Gumloop's Tasks filter). A segmented control over where the
// pattern's labels came from: measured from the caption or post data (caption level, never
// accepted by hand) or accepted by hand (spoken level), or only suggested by Claude. Each option
// after All carries the mark of its chip, filled for measured or accepted and outlined in the
// accent for Claude suggested, so the accent marks "Claude suggested" as everywhere else while
// the text stays ink. One raised thumb slides to the picked option (--motion-base; the global
// reduced-motion block in globals.css stops it). The thumb is placed from the picked button's own
// box, so it follows the label widths at every screen size, and it never slides on first paint.
// Before the page is live (server render) the picked button draws its own raised look instead.

import { useLayoutEffect, useRef } from "react";

import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

import type { LabelFilter } from "./types";

type LabelToggleProps = {
  value: LabelFilter;
  counts: Record<LabelFilter, number>;
  onChange: (value: LabelFilter) => void;
  className?: string;
};

const OPTIONS: LabelFilter[] = ["all", "accepted", "suggested"];

/** The chip mark for an option: filled (measured or accepted), outlined accent (suggested). From
 *  640px only: on a phone the three labels and their counts just fit the row without it. */
function ChipMark({ option }: { option: LabelFilter }) {
  if (option === "all") return null;
  return (
    <span
      aria-hidden
      data-chip-mark={option}
      className={cn(
        "size-2.5 shrink-0 rounded-[3px] border max-sm:hidden",
        option === "accepted" ? "border-muted-foreground/60 bg-muted-foreground/30" : "border-indigo-accent",
      )}
    />
  );
}

export function LabelToggle({ value, counts, onChange, className }: LabelToggleProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const track = trackRef.current;
    const thumb = thumbRef.current;
    if (!track || !thumb) return;
    const place = () => {
      const picked = track.querySelector<HTMLElement>(`[data-label="${value}"]`);
      if (!picked) return;
      thumb.style.width = `${picked.offsetWidth}px`;
      thumb.style.transform = `translateX(${picked.offsetLeft}px)`;
    };
    place();
    // Placed before the first paint without a slide; from the next frame on, a pick slides.
    if (!track.hasAttribute("data-thumb")) track.setAttribute("data-thumb", "placed");
    const frame = window.requestAnimationFrame(() => track.setAttribute("data-thumb", "ready"));
    // Web fonts and screen width change the label widths: place it again when any box resizes.
    const watch = new ResizeObserver(place);
    watch.observe(track);
    for (const button of track.querySelectorAll("[data-label]")) watch.observe(button);
    return () => {
      window.cancelAnimationFrame(frame);
      watch.disconnect();
    };
  }, [value]);

  return (
    <div
      ref={trackRef}
      data-layer="ui"
      data-label-toggle
      role="group"
      aria-label={copy.patterns.labels.label}
      className={cn(
        "relative inline-flex h-9 items-center rounded-md border border-line bg-subtle p-0.5 pointer-coarse:h-11",
        className,
      )}
    >
      <span
        ref={thumbRef}
        aria-hidden
        data-toggle-thumb
        className={cn(
          "pointer-events-none absolute inset-y-0.5 left-0 rounded-[4px] border border-line bg-surface opacity-0",
          "in-data-[thumb]:opacity-100",
          "in-data-[thumb=ready]:transition-[transform,width] in-data-[thumb=ready]:duration-(--motion-base) in-data-[thumb=ready]:ease-(--motion-ease)",
        )}
      />
      {OPTIONS.map((key) => {
        const active = value === key;
        return (
          <button
            key={key}
            type="button"
            data-label={key}
            aria-pressed={active}
            onClick={() => onChange(key)}
            className={cn(
              "tap-target relative flex h-full min-w-0 items-center justify-center gap-1.5 rounded-[4px] border border-transparent px-2 text-ui whitespace-nowrap transition-colors duration-(--motion-fast) sm:px-2.5",
              key === "all" ? "shrink-0" : "flex-auto sm:flex-none",
              active
                ? "border-line bg-surface text-foreground in-data-[thumb]:border-transparent in-data-[thumb]:bg-transparent"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <ChipMark option={key} />
            <span className="truncate">{copy.patterns.labels[key]}</span>
            <span className="font-sans text-muted-foreground tabular-nums">{counts[key]}</span>
          </button>
        );
      })}
    </div>
  );
}
