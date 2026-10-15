"use client";

// The patterns screen body. Top: the short "seen more in outliers" list, its meaning behind an
// (i). Then the catalog (Steep) on the left from 1024px, and on the right the "All | Accepted |
// Claude suggested" toggle (mymind) over one bordered list: a sticky key row (the Outliers /
// Normal swatches and the one (i) about the groups: definitions, caveat notes, population), a
// group per kind in the fixed catalog order, a row per pattern in the order the laptop built
// them. Outlier bars and dots are the counts teal, normal ones grey. Never sorted by a count, no
// ratio column, no leaderboard. Patterns no counted outlier carries fold away at the end of their
// group. A #p-... hash opens that pattern. Round 3 text cut: no stamp, no legend card, no fold
// body; what they said sits in the (i).

import { ChevronRightIcon } from "lucide-react";
import { useEffect, useMemo, useState, type MouseEvent } from "react";

import { InfoHint } from "@/components/shared/info-hint";
import { LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { copy, fmt } from "@/lib/copy";
import type { PatternsPage } from "@/lib/hosted";
import { cn } from "@/lib/utils";

import { CatalogTree } from "./catalog-tree";
import { CompareBars, GroupDot } from "./compare-bars";
import { GroupsHint } from "./group-legend";
import { LabelToggle } from "./label-toggle";
import { PatternLabel, PatternRow } from "./pattern-row";
import { KIND_ORDER, groupSizes, shortLabel, type KindFilter, type LabelFilter, type Pattern } from "./types";

function matchesLabel(p: Pattern, label: LabelFilter): boolean {
  return label === "all" || (label === "suggested" ? p.suggested : !p.suggested);
}

export function PatternsView({ page }: { page: PatternsPage }) {
  const [kind, setKind] = useState<KindFilter>("all");
  const [label, setLabel] = useState<LabelFilter>("all");
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [zeroOpen, setZeroOpen] = useState<Set<string>>(() => new Set());

  const sizes = useMemo(() => groupSizes(page.patterns), [page.patterns]);
  const labelCounts = useMemo(
    () => ({
      all: page.patterns.length,
      accepted: page.patterns.filter((p) => !p.suggested).length,
      suggested: page.patterns.filter((p) => p.suggested).length,
    }),
    [page.patterns],
  );
  const tabLabel = useMemo(() => new Map(page.tabs.map((t) => [t.key, t.label])), [page.tabs]);
  const shown = page.patterns.filter((p) => (kind === "all" || p.kind === kind) && matchesLabel(p, label));
  const kinds = KIND_ORDER.filter((k) => kind === "all" || k === kind);

  function reveal(anchor: string) {
    const p = page.patterns.find((x) => x.anchor === anchor);
    if (!p) return;
    setKind("all");
    setLabel("all");
    setOpen((s) => new Set(s).add(anchor));
    if (p.zero) setZeroOpen((s) => new Set(s).add(p.kind));
    window.requestAnimationFrame(() => document.getElementById(anchor)?.scrollIntoView({ block: "start" }));
  }

  // A link from the board or a reel lands on /patterns#p-...: open that pattern once.
  useEffect(() => {
    const anchor = decodeURIComponent(window.location.hash.slice(1));
    if (!anchor.startsWith("p-")) return;
    const id = window.requestAnimationFrame(() => reveal(anchor));
    return () => window.cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggle(anchor: string) {
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(anchor)) next.delete(anchor);
      else next.add(anchor);
      return next;
    });
  }

  function toggleZero(k: string) {
    setZeroOpen((s) => {
      const next = new Set(s);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-6">
      {page.lead.length ? (
        <section data-layer="ui" data-lead aria-labelledby="patterns-lead" className="flex flex-col gap-2">
          {/* The teal dot says "outliers" without a word; what "seen more" means sits in the (i),
              beside the heading, never inside it. */}
          <div className="flex items-center gap-1.5">
            <h2 id="patterns-lead" className="flex items-center gap-2 text-sm font-medium">
              <GroupDot group="o" className="size-2.5" />
              {copy.patterns.lead.title}
            </h2>
            <InfoHint label={fmt(copy.ui.hintAbout, { topic: copy.patterns.lead.title })} side="bottom" align="start">
              {copy.patterns.lead.note}
            </InfoHint>
          </div>
          <ul className="flex flex-col divide-y divide-line rounded-xl border border-line bg-surface">
            {page.lead.map((l) => {
              const lp = page.patterns.find((p) => p.anchor === l.anchor);
              const go = (e: MouseEvent<HTMLAnchorElement>) => {
                e.preventDefault();
                window.history.replaceState(null, "", `#${l.anchor}`);
                reveal(l.anchor);
              };
              if (lp?.bars) {
                // The same label and paired bars as the row below (Pinterest Compare's
                // Categories table). A screen reader hears the chip and each bar's own label,
                // the same as the row below; no hidden copy of the data's line (round 3).
                return (
                  <li key={l.anchor}>
                    <a
                      href={`#${l.anchor}`}
                      data-row
                      onClick={go}
                      className="grid min-h-9 w-full grid-cols-[minmax(0,1fr)_16px] items-center gap-x-3 gap-y-1.5 px-3 py-2 text-left hover:bg-subtle/50 pointer-coarse:min-h-11 sm:grid-cols-[minmax(0,1fr)_minmax(180px,38%)_16px]"
                    >
                      <span className="min-w-0">
                        <PatternLabel pattern={lp} />
                      </span>
                      <ChevronRightIcon aria-hidden className="size-4 justify-self-end text-muted-foreground sm:order-last" />
                      <CompareBars pattern={lp} className="col-span-2 sm:col-span-1" />
                    </a>
                  </li>
                );
              }
              // No bars to show: the short name on one line; the full name and the outlier stat
              // are its hover text (round 4: no sub-text under rows).
              const sep = ` ${copy.lab.header.sep} `;
              const cut = l.text.lastIndexOf(sep);
              const name = cut > 0 ? l.text.slice(0, cut) : l.text;
              return (
                <li key={l.anchor}>
                  <a
                    href={`#${l.anchor}`}
                    data-row
                    onClick={go}
                    title={l.text}
                    className="flex min-h-9 items-center gap-2 px-3 py-2 text-ui hover:bg-subtle/50 pointer-coarse:min-h-11"
                  >
                    <span className="flex min-w-0 flex-1">
                      <LayerValue layer="counts">{shortLabel(name)}</LayerValue>
                    </span>
                    <ChevronRightIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                  </a>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <div className="flex flex-col gap-4 lg:grid lg:grid-cols-[176px_minmax(0,1fr)] lg:items-start lg:gap-6">
        <CatalogTree tabs={page.tabs} total={page.patterns.length} value={kind} onChange={setKind} className="lg:sticky lg:top-16" />

        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <LabelToggle value={label} counts={labelCounts} onChange={setLabel} className="w-full sm:w-auto" />
            {shown.length !== page.patterns.length ? (
              <span data-layer="ui" data-showing className="text-ui text-muted-foreground">
                {fmt(copy.patterns.showing, { n: shown.length, total: page.patterns.length })}
              </span>
            ) : null}
          </div>

          {/* overflow-clip, not hidden: hidden would make the card a scroll box and the key
              row below would stop sticking under the top bar. */}
          <section data-layer="ui" data-pattern-list className="overflow-clip rounded-xl border border-line bg-surface">
            {/* The dot key stays over the list while it scrolls (Copilot Categories' column
                header), with the one (i) about the groups at its end. One row at every width:
                from 640px it is the column header (Pattern | Outliers Normal | chevron). */}
            <div
              data-list-key
              className="sticky top-topbar z-10 flex h-9 items-center gap-x-3 border-b border-line bg-surface px-3 text-mono text-muted-foreground pointer-coarse:h-11 sm:grid sm:grid-cols-[minmax(0,1fr)_minmax(180px,38%)_16px]"
            >
              <span className="hidden items-center gap-2 sm:flex">
                {copy.patterns.columns.pattern}
                <LayerTag layer="shape" />
              </span>
              <span className="flex min-w-0 flex-1 items-center gap-1.5">
                <GroupDot group="o" />
                {copy.patterns.legend.outliers}
                <GroupDot group="m" className="ml-2" />
                {copy.patterns.legend.normal}
                <LayerTag layer="counts" className="ml-1 max-sm:hidden" />
                <GroupsHint
                  outliersN={sizes.o}
                  normalN={sizes.m}
                  population={page.population}
                  notes={page.notes}
                  className="ml-auto sm:ml-1"
                />
              </span>
              <span className="hidden sm:block" />
            </div>

            {kinds.map((k) => {
              const rows = shown.filter((p) => p.kind === k);
              const counted = rows.filter((p) => !p.zero);
              const zero = rows.filter((p) => p.zero);
              const zeroIsOpen = zeroOpen.has(k);
              if (kind === "all" && rows.length === 0) return null;
              return (
                <div key={k} data-group-kind={k} className="border-b border-line last:border-b-0">
                  {/* The count is of the rows shown under the header; the fold below says its own. */}
                  <h3 className="flex h-8 items-center gap-2 border-b border-line bg-subtle/60 px-3 font-mono text-[10px] tracking-wide text-muted-foreground uppercase">
                    <span>{tabLabel.get(k) ?? k}</span>
                    {counted.length ? <span className="tabular-nums">{counted.length}</span> : null}
                  </h3>
                  {counted.length ? (
                    <ul className="flex flex-col divide-y divide-line">
                      {counted.map((p) => (
                        <PatternRow key={p.id} pattern={p} open={open.has(p.anchor)} onToggle={() => toggle(p.anchor)} />
                      ))}
                    </ul>
                  ) : null}
                  {zero.length ? (
                    <div data-zero-fold className={cn(counted.length && "border-t border-line")}>
                      <button
                        type="button"
                        aria-expanded={zeroIsOpen}
                        onClick={() => toggleZero(k)}
                        className="flex min-h-9 w-full items-center gap-2 px-3 py-1.5 text-left text-ui text-muted-foreground hover:bg-subtle/50 pointer-coarse:min-h-11"
                      >
                        <ChevronRightIcon aria-hidden className={cn("size-4 shrink-0 transition-transform", zeroIsOpen && "rotate-90")} />
                        <span className="font-medium text-foreground">{copy.patterns.zero.title}</span>
                        <span className="tabular-nums">{zero.length}</span>
                      </button>
                      <ul hidden={!zeroIsOpen} className="flex flex-col divide-y divide-line border-t border-line">
                        {zero.map((p) => (
                          <PatternRow key={p.id} pattern={p} open={open.has(p.anchor)} onToggle={() => toggle(p.anchor)} />
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {rows.length === 0 ? (
                    <p className="flex min-h-9 items-center px-3 py-2 text-ui text-muted-foreground">{copy.patterns.none}</p>
                  ) : null}
                </div>
              );
            })}
            {kind === "all" && shown.length === 0 ? (
              <p className="flex min-h-9 items-center px-3 py-2 text-ui text-muted-foreground">{copy.patterns.none}</p>
            ) : null}
          </section>
        </div>
      </div>
    </div>
  );
}
