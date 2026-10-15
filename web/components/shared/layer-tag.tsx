// A small mono tag naming a layer (COUNT, FACT, SHAPE, BRAIN), for column headers and section
// labels (Neon tables reference), led by the layer's colour dot. The tag itself is ui text about
// that layer; the text stays ink, only the dot is coloured (never a background fill, never a
// status: teal is the counts layer, not "good").

import { copy } from "@/lib/copy";
import type { Layer } from "@/lib/contract";
import { cn } from "@/lib/utils";

/** The layer's colour mark as an SVG dot (8px): counts teal, shape indigo, facts ink, brain a
 *  split cool/warm dot in a dotted ring (the diverging brain scale). Decorative: aria-hidden. */
export function LayerDot({ layer, className }: { layer: Exclude<Layer, "ui">; className?: string }) {
  return (
    <svg data-layer-dot={layer} aria-hidden viewBox="0 0 8 8" className={cn("size-2 shrink-0", className)}>
      {layer === "brain" ? (
        <>
          <path d="M4 1.25A2.75 2.75 0 0 0 4 6.75Z" className="fill-brain-cool" />
          <path d="M4 1.25A2.75 2.75 0 0 1 4 6.75Z" className="fill-brain-warm" />
          <circle cx="4" cy="4" r="3.6" fill="none" strokeWidth="0.7" strokeDasharray="0.9 0.9" className="stroke-current" />
        </>
      ) : (
        <circle
          cx="4"
          cy="4"
          r="3.25"
          className={layer === "counts" ? "fill-counts" : layer === "shape" ? "fill-shape" : "fill-facts"}
        />
      )}
    </svg>
  );
}

export function LayerTag({ layer, className }: { layer: Exclude<Layer, "ui">; className?: string }) {
  return (
    <span
      data-layer="ui"
      data-tag-layer={layer}
      className={cn(
        "inline-flex h-4 items-center gap-1 rounded-sm border border-line px-1 font-mono text-[10px] leading-none tracking-wide text-muted-foreground",
        layer === "brain" && "border-dotted",
        className,
      )}
    >
      <LayerDot layer={layer} className="size-1.5" />
      {copy.layers.tags[layer]}
    </span>
  );
}
