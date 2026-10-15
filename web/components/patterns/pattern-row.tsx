"use client";

// One pattern: its shape label on the left, the outliers vs normal bars on the right (Pinterest
// Compare reference). Clicking the row opens its source reels underneath: the family and level,
// the slot, the per-creator contrast and the outlier reels with their plays (the only place plays
// and x show on this page). Analysis only (D31): no drafts and no Recreate here. Names are cut
// to a few words in the row (the full name is its hover text).

import { ArrowUpRightIcon, ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { ShapeChip } from "@/components/shared/shape-chip";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

import { CompareBars } from "./compare-bars";
import { shortLabel, type Pattern } from "./types";

type PatternRowProps = {
  pattern: Pattern;
  open: boolean;
  onToggle: () => void;
};

function Flag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex h-5 shrink-0 items-center rounded-sm border border-line px-1 font-mono text-mono leading-none tracking-wide text-muted-foreground">
      {children}
    </span>
  );
}

function DetailBlock({ title, tag, children, className }: { title: string; tag?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <div className="flex items-center gap-2 text-mono text-muted-foreground">
        <span className="font-medium">{title}</span>
        {tag}
      </div>
      {children}
    </div>
  );
}

/** The left half of a row: the shape chip with its flags. The family and level sit in the open
 *  row (round 3 text cut). The "seen more in outliers" list reuses it so its rows read the same
 *  as the list below. */
export function PatternLabel({ pattern: p }: { pattern: Pattern }) {
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1.5">
      <ShapeChip
        label={shortLabel(p.label)}
        title={p.label}
        status={p.suggested ? "suggested" : "accepted"}
        hint={!p.suggested && p.level === "caption" ? copy.shape.measuredHint : undefined}
      />
      {p.show_new ? <Flag>{copy.patterns.flags.new}</Flag> : null}
      {p.show_few ? <Flag>{copy.patterns.flags.few}</Flag> : null}
    </span>
  );
}

export function PatternRow({ pattern: p, open, onToggle }: PatternRowProps) {
  const panelId = `${p.anchor}-reels`;
  return (
    <li id={p.anchor} data-pattern-row={p.id} data-kind={p.kind} data-open={open} className="scroll-mt-28">
      <button
        type="button"
        data-row
        data-row-summary
        aria-expanded={open}
        aria-controls={panelId}
        title={fmt(copy.patterns.detail.show, { label: p.label })}
        onClick={onToggle}
        className={cn(
          "grid w-full grid-cols-[minmax(0,1fr)_16px] items-center gap-x-3 gap-y-2 px-3 py-2 text-left hover:bg-subtle/50",
          "sm:grid-cols-[minmax(0,1fr)_minmax(180px,38%)_16px]",
          open && "bg-subtle/50",
        )}
      >
        <PatternLabel pattern={p} />
        <ChevronRightIcon
          aria-hidden
          className={cn("size-4 justify-self-end text-muted-foreground transition-transform sm:order-last", open && "rotate-90")}
        />
        <CompareBars pattern={p} className="col-span-2 sm:col-span-1" />
      </button>

      {open ? (
        <div id={panelId} data-pattern-detail className="grid gap-5 border-t border-line bg-subtle/30 px-3 py-4 md:grid-cols-2 md:gap-6">
          <div className="flex min-w-0 flex-col gap-4">
            <span data-pattern-family className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-mono text-muted-foreground">
              {p.family ? <LayerValue layer="shape">{p.family}</LayerValue> : null}
              <LayerValue layer="ui" className="font-mono">
                {p.level_tag}
              </LayerValue>
            </span>

            <DetailBlock title={copy.patterns.detail.slot} tag={<LayerTag layer="shape" />}>
              <LayerValue layer="shape" as="p" className="text-ui">
                {p.slot}
              </LayerValue>
              {p.same ? (
                <LayerValue layer="shape" as="p" className="text-ui text-muted-foreground">
                  {p.same}
                </LayerValue>
              ) : null}
            </DetailBlock>

            {p.by_creator.length ? (
              <DetailBlock title={copy.patterns.detail.byCreator} tag={<LayerTag layer="counts" />}>
                <ul className="flex flex-col gap-1">
                  {p.by_creator.map((line) => (
                    <li key={line} data-row>
                      <LayerValue layer="counts" className="text-ui">
                        {line}
                      </LayerValue>
                    </li>
                  ))}
                </ul>
              </DetailBlock>
            ) : null}

            {!p.bars ? (
              <LayerValue layer="counts" as="p" className="text-ui text-muted-foreground">
                {p.contrast}
              </LayerValue>
            ) : null}

            {p.seen || p.completeness ? (
              <div className="flex flex-col gap-0.5 text-mono text-muted-foreground">
                {p.seen ? <LayerValue layer="ui">{p.seen}</LayerValue> : null}
                {p.completeness ? <LayerValue layer="ui">{p.completeness}</LayerValue> : null}
              </div>
            ) : null}
          </div>

          <div className="flex min-w-0 flex-col gap-4">
            <DetailBlock title={copy.patterns.detail.sources} tag={<LayerTag layer="counts" />}>
              {p.sources.length ? (
                <ul data-sources className="flex flex-col divide-y divide-line rounded-md border border-line bg-surface">
                  {p.sources.map((s) => (
                    <li
                      key={s.sc}
                      data-row
                      data-source={s.sc}
                      className="flex min-h-9 flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-1.5 pointer-coarse:min-h-11"
                    >
                      <LayerValue layer="ui" className="text-ui font-medium">
                        {s.who}
                      </LayerValue>
                      {s.in_swipe ? (
                        <Link
                          href={`/reels/${s.sc}`}
                          data-layer="ui"
                          title={copy.patterns.detail.openReel}
                          className="font-mono text-mono text-muted-foreground underline underline-offset-2 hover:text-foreground"
                        >
                          {s.sc}
                        </Link>
                      ) : s.url ? (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noreferrer"
                          data-layer="ui"
                          title={copy.patterns.detail.onInstagram}
                          className="inline-flex items-center gap-0.5 font-mono text-mono text-muted-foreground underline underline-offset-2 hover:text-foreground"
                        >
                          {s.sc}
                          <ArrowUpRightIcon aria-hidden className="size-3" />
                        </a>
                      ) : (
                        <LayerValue layer="ui" className="font-mono text-mono text-muted-foreground">
                          {s.sc}
                        </LayerValue>
                      )}
                      <LayerValue layer="counts" className="ml-auto text-right text-ui">
                        {s.counts}
                      </LayerValue>
                    </li>
                  ))}
                </ul>
              ) : (
                <LayerValue layer="ui" as="p" className="text-ui text-muted-foreground">
                  {p.sources_empty}
                </LayerValue>
              )}
            </DetailBlock>
          </div>
        </div>
      ) : null}
    </li>
  );
}
