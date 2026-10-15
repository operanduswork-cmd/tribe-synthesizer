// A time chip ("0:12" or "0:12-0:18") at the start of a row (Apollo reference). Mono, tabular,
// bordered; dotted when it marks a brain moment; accent only when selected.

import Link from "next/link";

import type { Layer } from "@/lib/contract";
import { cn } from "@/lib/utils";

type TimeChipProps = {
  time: string;
  /** The layer of the moment the chip points at. Default "facts". */
  layer?: Layer;
  /** Selected state, e.g. the playhead is on this moment. */
  active?: boolean;
  href?: string;
  onClick?: () => void;
  className?: string;
};

export function TimeChip({ time, layer = "facts", active = false, href, onClick, className }: TimeChipProps) {
  const cls = cn(
    "inline-flex h-5 shrink-0 items-center rounded-sm border px-1.5 font-mono text-mono tabular-nums",
    layer === "brain" ? "border-dotted border-muted-foreground/60" : "border-line",
    active ? "border-indigo-accent bg-indigo-soft text-indigo-accent" : "text-muted-foreground",
    // A clickable chip keeps its 20px look but gets a 44px hit area on touch (globals.css).
    (href || onClick) && "tap-target hover:text-foreground",
    className,
  );
  if (href) {
    return (
      <Link href={href} data-layer={layer} className={cls}>
        {time}
      </Link>
    );
  }
  if (onClick) {
    return (
      <button type="button" data-layer={layer} aria-pressed={active} onClick={onClick} className={cls}>
        {time}
      </button>
    );
  }
  return (
    <span data-layer={layer} className={cls}>
      {time}
    </span>
  );
}
