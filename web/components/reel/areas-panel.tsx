"use client";

// The Areas tab (D28): the predicted average-brain response averaged over each atlas area, second
// by second, for this one reel (PlanetScale Insights reference: quiet rows, each with a small
// sparkline). The seven Yeo-7 networks first, in atlas order, collapsed; a network opens to its
// HCP-MMP1 areas in atlas order (Yeo network, then Glasser index), each with a left and a right
// sparkline. Rows NEVER move and are never sorted by a value; there is no top-N and no filter
// (either would read as a ranking).
//
// Every sparkline shares ONE y-scale (the reel's colour scale, +-vmax), never one per row. A row is
// marked when its area is "coloured on the brain at this second": |mean| >= grey_below x vmax,
// the same threshold as the 3D colours; warm above 0, cool below (a 2px rule, a dot, a chevron).
// Round 3 (D30): no area count under each network and no "coloured at" line; that explanation and
// the atlas-names note sit behind the title's (i), the credits behind a "Credits" (i).
// The playhead in every sparkline is one CSS variable on the list (--t-pct), so a new second
// re-renders only the rows whose mark changes.
//
// Hover or focus a row and the 3D brain outlines that network's or area's points; hover the brain
// and the matching row is marked if it is on screen (never scrolled to). A tap pins a row and
// shows "Show on brain", which scrolls to the map (phone). The network series come with the page;
// the area series load when the tab first opens. Brain values only (counts never appear here).

import { ChevronDownIcon, ChevronRightIcon, ChevronUpIcon, CrosshairIcon } from "lucide-react";
import { memo, useCallback, useEffect, useState, type CSSProperties } from "react";

import { LayerTag } from "@/components/shared/layer-tag";
import { InfoHint } from "@/components/shared/info-hint";
import { Button } from "@/components/ui/button";
import type { BrainAreasPayload } from "@/lib/brain/format";
import { copy, fmt } from "@/lib/copy";
import { prefersReducedMotion } from "@/lib/use-reduced-motion";
import { cn } from "@/lib/utils";

import { loadAreasSettled, areasNow } from "./brain/assets";
import { clearFocus, focusId, setFocus, touchFocus, useBrainFocus, type BrainFocus } from "./brain/brain-focus";
import { BRAIN_ID, BrainCredits } from "./brain/brain-section";
import { LineIcon } from "./brain/line-icon";
import { onBrain, rowAt, type BrainView, type OnBrain } from "./brain/view";
import { DownloadMenu } from "./download-menu";
import { useReelTime } from "./reel-time";

const A = copy.reel.areas;
const B = copy.reel.brain;

const RULE: Record<OnBrain | "both", string> = {
  above: "border-l-brain-warm",
  below: "border-l-brain-cool",
  both: "[border-image:linear-gradient(var(--brain-warm)_50%,var(--brain-cool)_50%)_1]",
  none: "border-l-transparent",
};

function useAreaSeries(view: BrainView) {
  const [areas, setAreas] = useState<BrainAreasPayload | null>(() => areasNow(view));
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (areas) return;
    let live = true;
    loadAreasSettled(view)
      .then((a) => live && setAreas(a))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [view, areas, attempt]);
  return {
    areas,
    failed,
    retry: () => {
      setFailed(false);
      setAttempt((a) => a + 1);
    },
  };
}

function showOnBrain() {
  document.getElementById(BRAIN_ID)?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "center" });
}

export function AreasPanel({ view }: { view: BrainView }) {
  const { t } = useReelTime();
  const focus = useBrainFocus();
  const { areas, failed, retry } = useAreaSeries(view);
  const [open, setOpen] = useState<Set<number>>(() => new Set());
  const T = view.timeS.length;
  const row = rowAt(view.timeS, t);
  const tPct = row >= 0 ? ((row + 0.5) / T) * 100 : -100;
  const on = (v: number | undefined) => (row >= 0 ? onBrain(v, view) : "none");
  const hoverNet = focus?.kind === "area" ? view.atlas.network[focus.k] : null;

  const toggle = useCallback((n: number) => {
    setOpen((cur) => {
      const next = new Set(cur);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      return next;
    });
  }, []);

  return (
    <section data-chart="areas" aria-label={A.label} className="flex flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
        <div data-layer="ui" className="flex min-w-0 items-center gap-2">
          <h2 className="text-ui font-medium">{A.title}</h2>
          <LayerTag layer="brain" />
          <InfoHint label={fmt(copy.ui.hintAbout, { topic: A.title })} align="start">
            <span className="flex flex-col gap-2">
              <span>{A.hint}</span>
              <span>{A.marks}</span>
              <span>{A.atlasNames}</span>
            </span>
          </InfoHint>
        </div>
        <DownloadMenu view={view} />
      </header>

      <ol data-area-list="" className="flex flex-col px-2 py-1.5" style={{ "--t-pct": `${tPct}%` } as CSSProperties}>
        {view.atlas.yeo.map((name, i) => {
          const n = i + 1;
          const expanded = open.has(n);
          const ks = view.atlas.order.filter((k) => view.atlas.network[k] === n);
          return (
            <li key={n} className="flex flex-col">
              <NetworkRow
                n={n}
                name={name}
                series={view.networks[i]}
                view={view}
                on={on(view.networks[i]?.[row])}
                expanded={expanded}
                hover={focusId(focus) === `net-${n}` ? "self" : hoverNet === n ? "within" : null}
                pinned={focus?.kind === "net" && focus.n === n && focus.pinned}
                onToggle={toggle}
              />
              {expanded ? (
                areas ? (
                  <ol className="flex flex-col pb-1">
                    {ks.map((k) => (
                      <AreaRow
                        key={k}
                        k={k}
                        view={view}
                        left={areas.areas.hcp_left[k]}
                        right={areas.areas.hcp_right[k]}
                        onL={on(areas.areas.hcp_left[k]?.[row])}
                        onR={on(areas.areas.hcp_right[k]?.[row])}
                        hover={focus?.kind === "area" && focus.k === k ? (focus.side ?? "both") : null}
                        pinned={focus?.kind === "area" && focus.k === k && focus.from === "list" && focus.pinned}
                      />
                    ))}
                  </ol>
                ) : (
                  <div data-layer="ui" className="flex items-center gap-2 py-2 pl-10 text-[11px] text-muted-foreground">
                    {failed ? (
                      <>
                        {A.failed}
                        <Button size="xs" variant="outline" onClick={retry}>
                          {A.retry}
                        </Button>
                      </>
                    ) : (
                      <span className="animate-pulse">{A.loading}</span>
                    )}
                  </div>
                )
              ) : null}
            </li>
          );
        })}
      </ol>

      <BrainCredits className="border-t border-line px-4 py-3" />
    </section>
  );
}

type Hover = "self" | "within" | "left" | "right" | "both" | null;

function pin(f: BrainFocus, current: boolean) {
  setFocus(current ? null : f);
}

const NetworkRow = memo(function NetworkRow({
  n,
  name,
  series,
  view,
  on,
  expanded,
  hover,
  pinned,
  onToggle,
}: {
  n: number;
  name: string;
  series: number[] | undefined;
  view: BrainView;
  on: OnBrain;
  expanded: boolean;
  hover: Hover;
  pinned: boolean;
  onToggle: (n: number) => void;
}) {
  const id = `net-${n}`;
  const self: BrainFocus = { kind: "net", n, from: "list", pinned: false };
  return (
    <div
      data-row=""
      data-area-id={id}
      data-on={on}
      data-hover={hover ?? undefined}
      className={cn(
        "group/row flex min-h-10 items-center gap-2 rounded-md border-l-2 py-1 pr-2 pl-1 transition-colors hover:bg-subtle pointer-coarse:min-h-11",
        RULE[on],
        hover && "bg-subtle",
      )}
      onPointerEnter={(e) => e.pointerType === "mouse" && touchFocus(self)}
      onPointerLeave={(e) => e.pointerType === "mouse" && clearFocus(id)}
      onFocus={() => touchFocus(self)}
      onBlur={() => clearFocus(id)}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("button")) return;
        pin({ ...self, pinned: true }, pinned);
      }}
    >
      <button
        type="button"
        aria-expanded={expanded}
        aria-label={fmt(expanded ? A.collapse : A.expand, { network: name })}
        onClick={() => onToggle(n)}
        className="tap-target inline-flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-foreground"
      >
        <ChevronRightIcon aria-hidden className={cn("size-4 transition-transform", expanded && "rotate-90")} />
      </button>
      <span data-layer="brain" data-encoding="plain" className="min-w-0 flex-1 truncate text-ui">
        {name}
      </span>
      {pinned ? <ShowOnBrain /> : null}
      <Sparkline series={series} view={view} className="h-7 w-24 shrink-0 sm:w-32" />
      <OnMark on={on} />
    </div>
  );
});

const AreaRow = memo(function AreaRow({
  k,
  view,
  left,
  right,
  onL,
  onR,
  hover,
  pinned,
}: {
  k: number;
  view: BrainView;
  left: number[] | undefined;
  right: number[] | undefined;
  onL: OnBrain;
  onR: OnBrain;
  hover: Hover;
  pinned: boolean;
}) {
  const id = `hcp-${k}`;
  const line = view.atlas.line[k];
  const rule = onL === "none" ? onR : onR === "none" || onR === onL ? onL : "both";
  const self: BrainFocus = { kind: "area", k, side: null, from: "list", pinned: false };
  return (
    <li
      data-row=""
      data-area-id={id}
      data-on-left={onL}
      data-on-right={onR}
      data-hover={hover ?? undefined}
      tabIndex={0}
      className={cn(
        "ml-7 flex min-h-8 items-center gap-2 rounded-md border-l-2 py-0.5 pr-2 pl-2 outline-none transition-colors hover:bg-subtle focus-visible:ring-2 focus-visible:ring-indigo-accent pointer-coarse:min-h-11",
        RULE[rule],
        hover && "bg-subtle",
      )}
      onPointerEnter={(e) => e.pointerType === "mouse" && touchFocus(self)}
      onPointerLeave={(e) => e.pointerType === "mouse" && clearFocus(id)}
      onFocus={() => touchFocus(self)}
      onBlur={() => clearFocus(id)}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("button")) return;
        pin({ ...self, pinned: true }, pinned);
      }}
    >
      <span data-layer="brain" data-encoding="plain" className="w-16 shrink-0 truncate font-mono text-mono">
        {view.atlas.codes[k]}
      </span>
      <span className="flex w-4 shrink-0 justify-center text-muted-foreground" title={line ? copy.reel.timeline.lanes[line] : undefined}>
        {line ? <LineIcon line={line} /> : null}
        {line ? <span className="sr-only">{fmt(B.hover.feeds, { line: copy.reel.timeline.lanes[line] })}</span> : null}
      </span>
      <span className="flex-1" />
      {pinned ? <ShowOnBrain /> : null}
      <Side label={A.sideShort.left} name={B.hemi.left} series={left} view={view} on={onL} />
      <Side label={A.sideShort.right} name={B.hemi.right} series={right} view={view} on={onR} />
    </li>
  );
});

function Side({ label, name, series, view, on }: { label: string; name: string; series: number[] | undefined; view: BrainView; on: OnBrain }) {
  return (
    <span className="flex items-center gap-1">
      <span data-layer="ui" aria-label={name} className="w-2 text-[10px] text-muted-foreground">
        {label}
      </span>
      <Sparkline series={series} view={view} className="h-5 w-14 sm:w-20" />
      <Dot on={on} />
    </span>
  );
}

function ShowOnBrain() {
  return (
    <Button size="xs" variant="outline" onClick={showOnBrain} className="shrink-0">
      <CrosshairIcon aria-hidden />
      {A.showOnBrain}
    </Button>
  );
}

function Dot({ on }: { on: OnBrain }) {
  return (
    <span
      aria-hidden
      data-layer="brain"
      data-encoding="plain"
      className={cn(
        "size-2 shrink-0 rounded-full",
        on === "above" ? "bg-brain-warm" : on === "below" ? "bg-brain-cool" : "border border-line",
      )}
    />
  );
}

/** The mark at the selected second: a dot and a small up or down chevron (never colour alone;
 *  D30: a shape in place of the word, which stays as its accessible name), or an empty dot. */
function OnMark({ on }: { on: OnBrain }) {
  const Icon = on === "above" ? ChevronUpIcon : on === "below" ? ChevronDownIcon : null;
  const name = on === "above" ? B.legend.higher : on === "below" ? B.legend.lower : undefined;
  return (
    <span
      data-layer="brain"
      data-encoding="plain"
      data-on-mark={on}
      role={name ? "img" : undefined}
      aria-label={name}
      title={name}
      className="flex w-8 shrink-0 items-center gap-0.5 text-muted-foreground"
    >
      <Dot on={on} />
      {Icon ? <Icon aria-hidden className="size-3.5" /> : null}
    </span>
  );
}

/** One area's series on the panel's ONE scale (+-vmax, clipped there): warm fill above 0, cool
 *  below, the dotted line on top, a faint "near 0" band, and the playhead from --t-pct. */
const Sparkline = memo(function Sparkline({ series, view, className }: { series: number[] | undefined; view: BrainView; className?: string }) {
  const H = 20;
  const mid = H / 2;
  const n = series?.length ?? 0;
  const y = (v: number) => mid - Math.max(-1, Math.min(1, v / view.vmax)) * (mid - 1);
  let line = "";
  let up = "";
  let down = "";
  if (series && n) {
    const pts = series.map((v, i) => [i + 0.5, Number.isFinite(v) ? v : 0] as const);
    line = pts.map(([x, v], i) => `${i ? "L" : "M"}${x} ${y(v).toFixed(2)}`).join("");
    const area = (f: (v: number) => number) =>
      `M${pts[0][0]} ${mid}` + pts.map(([x, v]) => `L${x} ${y(f(v)).toFixed(2)}`).join("") + `L${pts[n - 1][0]} ${mid}Z`;
    up = area((v) => Math.max(0, v));
    down = area((v) => Math.min(0, v));
  }
  const band = view.greyBelow * (mid - 1);
  return (
    <span className={cn("relative block", className)}>
      <svg data-layer="brain" viewBox={`0 0 ${Math.max(1, n)} ${H}`} preserveAspectRatio="none" aria-hidden className="block size-full">
        <rect x={0} y={mid - band} width={Math.max(1, n)} height={band * 2} className="fill-brain-near/25" />
        {up ? <path d={up} className="fill-brain-warm-soft" /> : null}
        {down ? <path d={down} className="fill-brain-cool-soft" /> : null}
        <line x1={0} x2={Math.max(1, n)} y1={mid} y2={mid} vectorEffect="non-scaling-stroke" strokeWidth={1} className="stroke-line" />
        {line ? <path d={line} vectorEffect="non-scaling-stroke" strokeWidth={1.25} strokeLinejoin="round" className="brain-line fill-none stroke-foreground/70" /> : null}
      </svg>
      <span aria-hidden className="pointer-events-none absolute inset-y-0 w-px bg-indigo-accent/70" style={{ left: "var(--t-pct)" }} />
    </span>
  );
});
