// A status as a shape and its word (Tana to-do glyphs, GitHub's run marks, Vercel's "● Ready"
// references). Each status has its own ink glyph, so it reads without any colour: a ring waits,
// a turning arc works, a ticked disc is done, a ring with a cross, bars or a slash has stopped,
// a muted ring with a dash was cancelled. Never a red or green fill, never a layer
// colour. The running arc turns and the online runner rings out; both stop under reduced motion
// (the global block in app/globals.css).

import { JOB_STATUS_TONE, type DotTone, type JobStatusName } from "@/components/shared/status-dot";
import { copy } from "@/lib/copy";
import type { RunnerStatus } from "@/lib/data";
import { cn } from "@/lib/utils";

export type Glyph = "ring" | "spin" | "check" | "cross" | "pause" | "slash" | "minus" | "live" | "dot";

const JOB_GLYPH: Record<JobStatusName, Glyph> = {
  queued: "ring",
  running: "spin",
  done: "check",
  failed: "cross",
  interrupted: "pause",
  refused: "slash",
  cancelled: "minus",
};

/** The 12px glyph alone (decorative; the word beside it carries the meaning). */
export function StatusGlyph({ glyph, className }: { glyph: Glyph; className?: string }) {
  const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round" as const };
  if (glyph === "live") {
    return (
      <span aria-hidden data-glyph={glyph} className={cn("relative inline-flex size-3 shrink-0 items-center justify-center", className)}>
        <span className="absolute inset-0.5 animate-ping rounded-full bg-foreground/25 [animation-duration:2s]" />
        <svg viewBox="0 0 12 12" className="relative size-full">
          <circle cx="6" cy="6" r="4" fill="currentColor" />
        </svg>
      </span>
    );
  }
  return (
    <svg
      aria-hidden
      data-glyph={glyph}
      viewBox="0 0 12 12"
      className={cn(
        "size-3 shrink-0",
        glyph === "spin" && "animate-spin [animation-duration:1.4s]",
        (glyph === "minus" || glyph === "dot") && "text-muted-foreground",
        className,
      )}
    >
      {glyph === "check" ? (
        <>
          <circle cx="6" cy="6" r="5.25" fill="currentColor" />
          <path d="M3.7 6.2 5.3 7.7 8.4 4.5" {...stroke} className="stroke-surface" />
        </>
      ) : glyph === "spin" ? (
        <>
          <circle cx="6" cy="6" r="4.5" {...stroke} opacity="0.25" />
          <path d="M6 1.5A4.5 4.5 0 0 1 10.5 6" {...stroke} />
        </>
      ) : glyph === "dot" ? (
        <circle cx="6" cy="6" r="4" fill="currentColor" opacity="0.6" />
      ) : (
        <>
          {/* A plain ring waits; a thinner, wider ring holds the mark of a stopped or cancelled job. */}
          <circle cx="6" cy="6" r={glyph === "ring" ? 4.5 : 5} {...stroke} strokeWidth={glyph === "ring" ? 1.5 : 1.2} />
          {glyph === "cross" ? <path d="M4.3 4.3l3.4 3.4M7.7 4.3l-3.4 3.4" {...stroke} strokeWidth={1.4} /> : null}
          {glyph === "pause" ? <path d="M4.6 4.1v3.8M7.4 4.1v3.8" {...stroke} strokeWidth={1.4} /> : null}
          {glyph === "slash" ? <path d="M2.5 9.5 9.5 2.5" {...stroke} strokeWidth={1.2} /> : null}
          {glyph === "minus" ? <path d="M4 6h4" {...stroke} strokeWidth={1.4} /> : null}
        </>
      )}
    </svg>
  );
}

type StatusMarkProps = {
  glyph: Glyph;
  /** The dot tone the rest of the site uses for this status (data-tone, for tests and styles). */
  tone: DotTone;
  /** The word after the glyph (from copy). */
  label: string;
  glyphClassName?: string;
  className?: string;
};

export function StatusMark({ glyph, tone, label, glyphClassName, className }: StatusMarkProps) {
  return (
    <span data-layer="ui" data-tone={tone} className={cn("inline-flex items-center gap-1.5", className)}>
      <StatusGlyph glyph={glyph} className={glyphClassName} />
      <span>{label}</span>
    </span>
  );
}

/** A job's status as its glyph and word. */
export function JobStatusMark({ status, className }: { status: JobStatusName; className?: string }) {
  return <StatusMark glyph={JOB_GLYPH[status]} tone={JOB_STATUS_TONE[status]} label={copy.status[status]} className={className} />;
}

/** The runner's state as its glyph and word: online rings out, paused shows bars in a dashed ring. */
export function runnerMark(status: RunnerStatus): { glyph: Glyph; tone: DotTone; word: string } {
  if (status.paused) return { glyph: "pause", tone: "dashed", word: copy.runner.paused };
  switch (status.state) {
    case "online":
      return { glyph: "live", tone: "solid", word: copy.runner.online };
    case "offline":
      return { glyph: "ring", tone: "hollow", word: copy.runner.offline };
    default:
      return { glyph: "dot", tone: "muted", word: copy.runner[status.state] };
  }
}
