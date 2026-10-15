"use client";

// The brain downloads, in the brain controls and the Areas header (Flodesk reference: one
// download icon in the chart header; Square: each option with a short line under it).
// - "Raw numbers (CSV)": /reels/[sc]/brain/csv, built on the server from the schema-checked page
//   (lib/brain/csv.ts): per second the four lines, the seven networks and every HCP area per side.
// - "Every surface point (CSV)": built here in the browser from the frames the brain already
//   loaded (or loads them now): one row per surface point, its side, area, network and line, then
//   one column per second, value = level / 127 x vmax at 4 decimals (stored at 255 levels on this
//   reel's one scale, so close to the model output, not exact). One reel only, never two.
// Both files start with "# " lines: the licence footer, the reel and job, what the values are and
// the atlas credits. A text cell that starts like a spreadsheet formula is refused, never written.

import { DownloadIcon, LoaderCircleIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

import type { BrainView } from "./brain/view";

const D = copy.reel.download;

const FORMULA_START = /^[=+\-@\t\r]/;

function text(cell: string): string {
  if (FORMULA_START.test(cell) || /[\r\n]/.test(cell)) throw new Error("a text cell would break the file");
  return `"${cell.replace(/"/g, '""')}"`;
}

/** The per-point numbers file, as text parts (one per line). */
export async function surfaceCsv(view: BrainView): Promise<string[]> {
  const { loadAtlas, loadFrames } = await import("./brain/assets");
  const [atlas, frames] = await Promise.all([loadAtlas(view), loadFrames(view)]);
  const C = D.csv;
  const comments = [
    C.footer,
    fmt(C.reel, { sc: view.sc }),
    fmt(C.job, { job: view.jobId }),
    C.surfaceUnits,
    C.oneReel,
    C.atlasNames,
    copy.reel.brain.credit.hcp,
    C.derived,
    C.yeo,
  ].map((l) => `# ${l}\n`);
  const seconds = view.timeS.map((s) => `s${Math.floor(s)}`);
  const out = [...comments, `vertex,hemisphere,area,network,feeds_line,${seconds.join(",")}\n`];
  const V = frames.vertices;
  const half = V / 2;
  // Only 255 stored levels exist, so each value's text is looked up, not formatted 860,000 times.
  const L = frames.levels;
  const table = Array.from({ length: 2 * L + 1 }, (_, i) => {
    const s = (((i - L) / L) * view.vmax).toFixed(4);
    return s === "-0.0000" ? "0.0000" : s;
  });
  const left = text(copy.reel.brain.hemi.left);
  const right = text(copy.reel.brain.hemi.right);
  const empty = text("");
  for (let v = 0; v < V; v++) {
    const k = atlas.hcp[v];
    const area = k ? text(view.atlas.codes[k - 1]) : empty;
    const net = k ? text(view.atlas.yeo[view.atlas.network[k - 1] - 1] ?? "") : empty;
    const line = k ? text(view.atlas.line[k - 1] ?? "") : empty;
    const vals = new Array<string>(frames.rows);
    for (let r = 0; r < frames.rows; r++) vals[r] = table[frames.q[r * V + v] + L];
    out.push(`${v},${v < half ? left : right},${area},${net},${line},${vals.join(",")}\n`);
  }
  return out;
}

function save(parts: BlobPart[], name: string, type: string) {
  const url = URL.createObjectURL(new Blob(parts, { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function DownloadMenu({ view, className, align = "end" }: { view: BrainView; className?: string; align?: "start" | "end" }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<"idle" | "building" | "failed">("idle");

  async function buildSurface() {
    setState("building");
    try {
      const parts = await surfaceCsv(view);
      save(parts, `tribe-${view.sc}-${view.jobId}-surface.csv`, "text/csv;charset=utf-8");
      setState("idle");
      setOpen(false);
    } catch {
      setState("failed");
    }
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={D.label} data-download-menu="" className={cn("text-muted-foreground", className)}>
          <DownloadIcon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} data-layer="ui" className="w-72 max-w-[calc(100vw-2rem)]">
        <DropdownMenuItem asChild className="pointer-coarse:min-h-11">
          <a href={view.urls.csv} download data-download="areas">
            <DownloadIcon aria-hidden className="text-muted-foreground" />
            {D.areas}
          </a>
        </DropdownMenuItem>
        <DropdownMenuItem
          data-download="surface"
          disabled={state === "building"}
          onSelect={(e) => {
            e.preventDefault();
            void buildSurface();
          }}
          className="pointer-coarse:min-h-11"
        >
          {state === "building" ? (
            <LoaderCircleIcon aria-hidden className="animate-spin text-muted-foreground" />
          ) : (
            <DownloadIcon aria-hidden className="text-muted-foreground" />
          )}
          {state === "building" ? D.building : D.surface}
        </DropdownMenuItem>
        <p className="px-1.5 pt-1 pb-1.5 text-[11px] leading-4 text-muted-foreground">{state === "failed" ? D.failed : D.hint}</p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
