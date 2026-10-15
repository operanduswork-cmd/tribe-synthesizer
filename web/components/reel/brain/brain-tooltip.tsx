"use client";

// The card for an area picked on the 3D brain (a DOM overlay, never text in the canvas): the HCP
// code and side, its Yeo network, the line it feeds (icon + name) or "not part of the four lines",
// and where its mean sits at the selected second on the reel's one scale. With a mouse it floats
// by the pointer and lets the pointer through; on touch a tap pins it under the canvas with a
// close button. All of it is brain text (data-layer="brain"); counts never appear here (D20).

import { XIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { clock, type LineKey } from "@/components/reel/time";
import type { BrainAreasPayload } from "@/lib/brain/format";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

import { areasNow, loadAreasSettled } from "./assets";
import { setFocus, useBrainFocus, useBrainPointer } from "./brain-focus";
import { LineIcon } from "./line-icon";
import { onBrain, rowAt, type BrainView } from "./view";

const B = copy.reel.brain;

type Mode = "float" | "card";

function useAreas(view: BrainView, want: boolean): BrainAreasPayload | null {
  const [areas, setAreas] = useState<BrainAreasPayload | null>(() => areasNow(view));
  useEffect(() => {
    if (!want || areas) return;
    let live = true;
    loadAreasSettled(view)
      .then((a) => live && setAreas(a))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [want, areas, view]);
  return areas;
}

export function BrainTooltip({ view, t, mode, box }: { view: BrainView; t: number | null; mode: Mode; box?: { w: number; h: number } }) {
  const focus = useBrainFocus();
  const pointer = useBrainPointer();
  const area = focus?.kind === "area" && focus.from === "brain" && focus.side ? focus : null;
  const show = Boolean(area) && (mode === "card" ? area!.pinned : !area!.pinned && pointer !== null);
  const areas = useAreas(view, Boolean(area));
  if (!area || !show) return null;

  const k = area.k;
  const side = area.side!;
  const net = view.atlas.network[k];
  const line = view.atlas.line[k] as LineKey | null;
  const row = rowAt(view.timeS, t ?? 0);
  const series = areas ? (side === "left" ? areas.areas.hcp_left : areas.areas.hcp_right)[k] : null;
  const value = series && row >= 0 ? series[row] : null;
  const state = onBrain(value, view);

  const body = (
    <>
      <p className="font-medium text-foreground">{fmt(B.hover.area, { area: view.atlas.codes[k], side: B.hemi[side] })}</p>
      <p>{fmt(B.hover.network, { network: view.atlas.yeo[net - 1] ?? "" })}</p>
      <p className="flex items-center gap-1.5">
        {line ? (
          <>
            <LineIcon line={line} />
            {fmt(B.hover.feeds, { line: copy.reel.timeline.lanes[line] })}
          </>
        ) : (
          B.hover.noLine
        )}
      </p>
      {value !== null ? (
        <p className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={cn(
              "size-2 shrink-0 rounded-full",
              state === "above" ? "bg-brain-warm" : state === "below" ? "bg-brain-cool" : "bg-brain-near",
            )}
          />
          {fmt(B.hover.at, { time: clock(t ?? 0), band: B.bands[state === "none" ? "near" : state] })}
        </p>
      ) : null}
    </>
  );

  if (mode === "card") {
    return (
      <div
        data-brain-tooltip="card"
        data-layer="brain"
        data-encoding="plain"
        className="relative flex flex-col gap-0.5 rounded-lg border border-line bg-surface p-3 pr-12 text-ui text-muted-foreground animate-appear"
      >
        {body}
        <button
          type="button"
          aria-label={copy.ui.close}
          onClick={() => setFocus(null)}
          className="tap-target absolute top-2 right-2 inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:text-foreground"
        >
          <XIcon aria-hidden className="size-4" />
        </button>
      </div>
    );
  }

  const p = pointer!;
  const flipX = box ? p.x > box.w * 0.55 : false;
  const flipY = box ? p.y > box.h * 0.5 : false;
  return (
    <div
      data-brain-tooltip="float"
      data-layer="brain"
      data-encoding="plain"
      role="status"
      className="pointer-events-none absolute z-10 flex w-max max-w-64 flex-col gap-0.5 rounded-lg border border-line bg-surface/95 px-3 py-2 text-[12px] leading-4 text-muted-foreground shadow-md backdrop-blur-sm"
      style={{
        left: p.x,
        top: p.y,
        transform: `translate(${flipX ? "calc(-100% - 12px)" : "12px"}, ${flipY ? "calc(-100% - 12px)" : "12px"})`,
      }}
    >
      {body}
    </div>
  );
}
