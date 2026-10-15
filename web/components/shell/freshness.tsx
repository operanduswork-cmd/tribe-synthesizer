// Data freshness, cut to one small grey line (round 3): "Data · 9 Oct", the day the hosted pages
// were rendered (meta.rendered_at, a ui date, neither a counts nor a brain value), and one (i)
// that opens to the four freshness sentences from the meta page, one line per layer, each led by
// the layer's colour dot (components/shared/layer-tag.tsx LayerDot; the text stays grey):
// "Counts as of …", "Facts fixed at ingest", "Shape labels last changed …", "TRIBE run …".
// Each sentence is its own line with its own data-layer, so a counts date and a brain date never
// share a line (D20). From 768px the line sits in the sidebar above the user menu; on a phone it
// is the strip under the top bar. Every dot sits in the same 10px slot, centred on the first
// line, so the sentences line up. The brain's split cool/warm dot draws at 10px (its dotted ring
// sits outside its core, so the core matches the 8px solid dots); nothing here animates.

import { InfoHint } from "@/components/shared/info-hint";
import { LayerDot } from "@/components/shared/layer-tag";
import { copy, fmt } from "@/lib/copy";
import { getMeta } from "@/lib/data";
import type { MetaPage } from "@/lib/hosted";
import { cn } from "@/lib/utils";

const LAYERS = ["counts", "facts", "shape", "brain"] as const;
type FreshLayer = (typeof LAYERS)[number];

const text = (meta: MetaPage | null, layer: FreshLayer) => meta?.layers[layer].text ?? copy.freshness[layer];

/** Facts are dates here, not mono values: the facts layer's mono style is turned off. */
const lineClass = (layer: FreshLayer) => cn("min-w-0", layer === "facts" && "font-sans text-[length:inherit] leading-[inherit]");

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

/** "Data · 9 Oct" from the meta page's render time, or "Data" when there is none. */
function label(meta: MetaPage | null): string {
  const d = meta ? new Date(meta.rendered_at) : null;
  return d && !Number.isNaN(d.getTime()) ? fmt(copy.freshness.short, { date: DAY.format(d) }) : copy.freshness.none;
}

/** The layer's dot in a fixed 10px slot, centred on the first line of its sentence. */
function DotSlot({ layer }: { layer: FreshLayer }) {
  return (
    <span className="flex h-lh w-2.5 shrink-0 items-center justify-center">
      <LayerDot layer={layer} className={layer === "brain" ? "size-2.5" : "size-2"} />
    </span>
  );
}

export function FreshnessList({ meta, layers = LAYERS, className }: { meta: MetaPage | null; layers?: readonly FreshLayer[]; className?: string }) {
  return (
    <ul aria-label={copy.topbar.freshness} data-freshness="list" className={cn("flex min-w-0 flex-col gap-y-1 text-muted-foreground", className)}>
      {layers.map((layer) => (
        <li key={layer} data-layer={layer} className={cn(lineClass(layer), "flex gap-1.5")}>
          <DotSlot layer={layer} />
          <span className="min-w-0">{text(meta, layer)}</span>
        </li>
      ))}
    </ul>
  );
}

/** The one small line and its (i). */
function FreshnessHint({ meta, where, side, align, className }: {
  meta: MetaPage | null;
  where: "sidebar" | "line";
  side: "right" | "bottom";
  align: "start" | "end";
  className?: string;
}) {
  return (
    <div data-layer="ui" data-freshness={where} className={cn("flex min-w-0 items-center gap-1.5 text-muted-foreground", className)}>
      <span data-freshness-label className="truncate">
        {label(meta)}
      </span>
      <InfoHint label={copy.topbar.freshness} side={side} align={align}>
        <FreshnessList meta={meta} className="text-ui" />
      </InfoHint>
    </div>
  );
}

/** The sidebar line (768px and up), above the user menu. */
export async function Freshness({ className }: { className?: string }) {
  const meta = await getMeta().catch(() => null);
  return <FreshnessHint meta={meta} where="sidebar" side="right" align="end" className={cn("h-6 text-ui", className)} />;
}

/** The phone strip under the top bar: the same line, its (i) opening below it. */
export async function FreshnessLine({ className }: { className?: string }) {
  const meta = await getMeta().catch(() => null);
  return (
    <FreshnessHint
      meta={meta}
      where="line"
      side="bottom"
      align="start"
      className={cn("min-h-9 text-[12px] leading-4 pointer-coarse:min-h-11", className)}
    />
  );
}
