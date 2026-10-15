// The Card tab: the counts strip as its own element above the card (D18), the snippet card
// exactly as strategist precomputed it (HOOK / HIGH / FLAT / TRY / TRY, or HOOK / BEATS / PACE /
// TRY / TRY without a TRIBE read) with its HIGH/FLAT footnote behind an (i) under the lines (D30),
// and the lock button for the private details, which the page shows in its header.
// Time chips sit at the start of each line (Apollo reference), except on HOOK, whose text ends
// "first word at" and reads on into its chip; every chip moves the timeline's playhead.
// Each tag leads with its colour dot (Gorgias / Linear tag reference): the layer's dot, warm for
// HIGH and cool for FLAT as on the timeline. The tag text stays muted ink.

import { LockIcon } from "lucide-react";

import { CopyCommand } from "@/components/shared/copy-command";
import { InfoHint } from "@/components/shared/info-hint";
import { LayerDot, LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import type { Layer } from "@/lib/contract";
import { copy } from "@/lib/copy";
import type { ReelPage } from "@/lib/hosted";
import { cn } from "@/lib/utils";

import { HintPopover } from "./hint-popover";
import { SeekChip } from "./reel-time";

type CardTag = ReelPage["card"]["lines"][number]["tag"];

/** The layer of each card line, as the hosted reel schema marks it. */
const LINE_LAYER: Record<CardTag, Layer> = {
  HOOK: "shape",
  HIGH: "brain",
  FLAT: "brain",
  TRY: "ui",
  BEATS: "shape",
  PACE: "facts",
};

/** Strategist joins the strip's items with the separator, spaced. */
const SEP = ` ${copy.reel.sep} `;

/** A card: the border darkens a little on hover (never a lift, never a fill). */
export const CARD_CLASS =
  "rounded-xl border border-line bg-surface transition-[border-color] duration-(--motion-base) ease-(--motion-ease) hover:border-foreground/20";
/** A row inside a card: a quiet background on hover. */
export const ROW_HOVER_CLASS = "transition-[background-color] duration-(--motion-fast) ease-(--motion-ease) hover:bg-subtle/60";

/** The colour mark before a card tag (8px SVG, decorative). HIGH warm and FLAT cool, each in the
 *  brain's dotted ring; HOOK and BEATS the shape dot, PACE the facts dot; TRY (ui) keeps the slot
 *  empty so the tags line up. */
function TagDot({ tag }: { tag: CardTag }) {
  const cls = "mr-1.5 inline-block size-2 align-[-0.05em]";
  if (tag === "HIGH" || tag === "FLAT") {
    return (
      <svg data-band-dot={tag === "HIGH" ? "above" : "below"} aria-hidden viewBox="0 0 8 8" className={cls}>
        <circle cx="4" cy="4" r="2.4" className={tag === "HIGH" ? "fill-brain-warm" : "fill-brain-cool"} />
        <circle cx="4" cy="4" r="3.6" fill="none" strokeWidth="0.7" strokeDasharray="0.9 0.9" className="stroke-current" />
      </svg>
    );
  }
  const layer = LINE_LAYER[tag];
  if (layer === "ui") return <span aria-hidden className={cls} />;
  return <LayerDot layer={layer} className={cls} />;
}

export function CountsStrip({ counts }: { counts: ReelPage["card"]["counts"] }) {
  // One short item each (Grain's meta row), so a line breaks between items, never mid-phrase,
  // and each line ends on the dot instead of starting with one.
  // The "as of" date repeats the counts stamp behind the Facts (i), so the strip drops it (text cut 2).
  const items = counts ? counts.text.split(SEP).filter((s) => !s.startsWith("as of ")) : [];
  return (
    <div data-row className={cn(CARD_CLASS, "flex items-start gap-2.5 px-4 py-2.5")} aria-label={copy.reel.strip.label}>
      <LayerTag layer="counts" className="mt-0.5 shrink-0" />
      {counts ? (
        <ul className="flex min-w-0 flex-wrap gap-x-1.5 gap-y-0.5 text-ui">
          {items.map((item, i) => (
            <li key={i} className="sm:whitespace-nowrap">
              <LayerValue layer="counts">{item}</LayerValue>
              {i < items.length - 1 ? (
                <span aria-hidden data-layer="ui" className="ml-1.5 text-muted-foreground">
                  {copy.reel.sep}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <span data-layer="ui" className="text-ui text-muted-foreground">
          {copy.reel.strip.none}
        </span>
      )}
    </div>
  );
}

export function SnippetCard({ card }: { card: ReelPage["card"] }) {
  // D31 (analysis only): the TRY lines stay in the data and are not drawn.
  const lines = (card.lines as ReadonlyArray<ReelPage["card"]["lines"][number]>).filter((ln) => ln.tag !== "TRY");
  return (
    <section aria-label={copy.reel.card.label} data-card-mode={card.mode} className={CARD_CLASS}>
      <ol className="divide-y divide-line">
        {lines.map((ln, i) => {
          const layer = LINE_LAYER[ln.tag];
          // The HOOK text ends "first word at": its chip reads after it, as on the laptop page.
          const chipAfter = ln.tag === "HOOK";
          return (
            <li
              key={i}
              data-row
              data-tag={ln.tag}
              className={cn(
                ROW_HOVER_CLASS,
                "grid grid-cols-[4rem_minmax(0,1fr)] items-baseline gap-x-3 px-4 py-2.5 first:rounded-t-xl pointer-coarse:py-3",
                !card.footnote && "last:rounded-b-xl",
              )}
            >
              <span data-layer="ui" className="font-mono text-[11px] tracking-wide whitespace-nowrap text-muted-foreground">
                <TagDot tag={ln.tag} />
                {ln.tag}
              </span>
              {chipAfter ? (
                // Inline flow: the chip follows "at" on the same line whenever that line has room.
                <span className="min-w-0">
                  <LayerValue layer={layer} data-card-text className="text-ui">
                    {ln.text}
                  </LayerValue>
                  {ln.time ? <SeekChip time={ln.time} layer={layer} className="ml-1.5 translate-y-px align-baseline" /> : null}
                  {"edge" in ln && ln.edge ? (
                    <span data-layer="brain" data-encoding="plain" className="ml-2 font-mono text-[11px] text-muted-foreground">
                      {copy.reel.card.edge}
                    </span>
                  ) : null}
                </span>
              ) : (
                <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                  {ln.time ? <SeekChip time={ln.time} layer={layer} className="translate-y-px" /> : null}
                  <LayerValue layer={layer} data-card-text className="min-w-0 text-ui">
                    {ln.text}
                  </LayerValue>
                  {"edge" in ln && ln.edge ? (
                    <span data-layer="brain" data-encoding="plain" className="font-mono text-[11px] text-muted-foreground">
                      {copy.reel.card.edge}
                    </span>
                  ) : null}
                </span>
              )}
            </li>
          );
        })}
      </ol>
      {/* The HIGH/FLAT footnote (D18) sits behind an (i) under the lines, word for word (D30). */}
      {card.footnote ? (
        <div data-card-footnote="" className="flex justify-end border-t border-line px-2.5 py-1">
          <InfoHint label={copy.reel.card.footnoteLabel} layer="brain" align="end">
            {card.footnote}
          </InfoHint>
        </div>
      ) : null}
    </section>
  );
}

/** The private details (D19): one lock button whose popover holds the note and the two laptop
 *  command (D31: analysis only, so no recreate row). */
export function PrivateButton({ localCmd }: { localCmd: string }) {
  const P = copy.reel.private;
  return (
    <span data-private-row="" className="inline-flex">
      <HintPopover
        label={P.title}
        trigger={<LockIcon aria-hidden className="size-4" />}
        align="end"
        side="bottom"
        className="size-8 border border-line bg-surface"
        contentClassName="w-96 gap-3"
        contentData={{ "data-private-details": "" }}
      >
        <span className="flex flex-col gap-1">
          <span className="font-medium">{P.title}</span>
          <span className="text-muted-foreground">{P.body}</span>
        </span>
        <CopyCommand command={localCmd} label={null} />
      </HintPopover>
    </span>
  );
}
