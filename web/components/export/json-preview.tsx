"use client";

// The raw JSON of the export, exactly what the Download button gives (the text is built on the
// server by lib/export-data.ts and passed in). Monospace, first PREVIEW_LINES lines with a "Show
// all" toggle, scrolls inside its own box so the page never scrolls sideways, a Copy button, one
// stats line and the Download link beside it. Syntax tint uses existing tokens only.

import { CheckIcon, CopyIcon, EyeIcon, EyeOffIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { buttonVariants } from "@/components/ui/button";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

const PREVIEW_LINES = 200;
const TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

/** One JSON line as tinted spans: keys, strings, numbers. */
function Line({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) parts.push(text.slice(last, at));
    const cls = m[1] ? (m[2] ? "text-[var(--indigo)]" : "text-[var(--counts)]") : "text-[var(--brain-warm)]";
    parts.push(
      <span key={i++} className={cls}>
        {m[1] ?? m[3]}
      </span>,
    );
    if (m[2]) parts.push(m[2]);
    last = at + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

export function JsonPreview({ text, reels, brain }: { text: string; reels: number; brain: number }) {
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  const [copied, setCopied] = useState(false);
  const lines = useMemo(() => text.split("\n"), [text]);
  const shown = all ? lines : lines.slice(0, PREVIEW_LINES);
  const kb = Math.max(1, Math.round(new Blob([text]).size / 1024));

  async function onCopy() {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      // No clipboard permission (or an insecure origin): fall back to a hidden textarea.
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      ta.remove();
    }
    setCopied(ok);
    if (ok) window.setTimeout(() => setCopied(false), 1600);
  }

  const btn = cn(buttonVariants({ variant: "outline", size: "lg" }), "min-h-11 px-4");
  return (
    <section data-export-preview="" aria-label={copy.export.previewTitle} className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <p data-export-stats="" className="mr-auto text-xs text-muted-foreground tabular-nums">
          {fmt(copy.export.stats, { kb, reels, brain })}
        </p>
        <button type="button" onClick={onCopy} data-export-copy="" className={btn} aria-live="polite">
          {copied ? <CheckIcon aria-hidden className="size-4" /> : <CopyIcon aria-hidden className="size-4" />}
          {copied ? copy.export.copied : copy.export.copy}
        </button>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          data-export-open=""
          className={btn}
        >
          {open ? <EyeOffIcon aria-hidden className="size-4" /> : <EyeIcon aria-hidden className="size-4" />}
          {open ? copy.export.hidePreview : copy.export.showPreview}
        </button>
        <Link href="/import" data-export-import="" className={btn}>
          {copy.import.exportLink}
        </Link>
        <a
          href="/export/data"
          download
          data-export-download=""
          className={cn(buttonVariants({ variant: "default", size: "lg" }), "min-h-11 px-4")}
        >
          {copy.export.button}
        </a>
      </div>
      {open ? (
      <pre
        data-export-json=""
        tabIndex={0}
        aria-label={copy.export.previewTitle}
        className="mt-3 max-h-[60vh] min-w-0 overflow-auto sleek-card rounded-lg p-3 font-mono text-xs leading-5 text-foreground"
      >
        {shown.map((l, n) => (
          <span key={n} className="block whitespace-pre">
            <Line text={l} />
          </span>
        ))}
      </pre>
      ) : null}
      {open && lines.length > PREVIEW_LINES ? (
        <button
          type="button"
          data-export-toggle=""
          onClick={() => setAll((v) => !v)}
          className={cn(buttonVariants({ variant: "outline", size: "lg" }), "mt-3 min-h-11 px-4")}
        >
          {fmt(all ? copy.export.showLess : copy.export.showAll, { lines: all ? PREVIEW_LINES : lines.length })}
        </button>
      ) : null}
    </section>
  );
}
