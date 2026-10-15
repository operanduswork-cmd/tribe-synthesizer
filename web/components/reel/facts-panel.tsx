// The Facts tab: the facts worked out on the laptop (length, first word, pace, call to action,
// text at 0:00) in Geist Mono, values only (D30). One (i) by the title opens to where the facts
// come from, "About this data" (one stamp per layer, each on its own row, led by its layer tag)
// and the wall sentence, word for word.

import { InfoHint } from "@/components/shared/info-hint";
import { LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { copy } from "@/lib/copy";
import type { ReelPage } from "@/lib/hosted";
import { cn } from "@/lib/utils";

import { CARD_CLASS, ROW_HOVER_CLASS } from "./reel-card";

const F = copy.reel.facts;

export function FactsPanel({ reel }: { reel: ReelPage }) {
  const stamps: Array<{ layer: "counts" | "shape" | "brain"; text: string | null }> = [
    { layer: "counts", text: reel.stamps.counts },
    { layer: "shape", text: reel.stamps.shape },
    { layer: "brain", text: reel.stamps.brain },
  ];
  return (
    <section className={CARD_CLASS}>
      <header data-layer="ui" className="flex items-center gap-2 border-b border-line px-4 py-2">
        <LayerTag layer="facts" />
        <h2 className="text-ui font-medium">{F.title}</h2>
        <InfoHint label={F.about} align="start" contentClassName="w-80">
          <div className="flex flex-col gap-3">
            <p data-facts-source="">{F.hint}</p>
            <div className="flex flex-col gap-1.5">
              <p className="font-medium">{F.about}</p>
              <ul data-stamps="" className="flex flex-col gap-1.5">
                {stamps.map((s) =>
                  s.text ? (
                    <li key={s.layer} data-row className="flex items-start gap-2">
                      <LayerTag layer={s.layer} className="mt-0.5 w-11 shrink-0 justify-center" />
                      <LayerValue layer={s.layer} className="min-w-0">
                        {s.text}
                      </LayerValue>
                    </li>
                  ) : null,
                )}
                <li data-row className="pl-[3.25rem] text-[11px] leading-4 text-muted-foreground">
                  {reel.stamps.page}
                </li>
              </ul>
            </div>
            <p data-wall="" className="text-muted-foreground">
              {F.wall}
            </p>
          </div>
        </InfoHint>
      </header>
      {reel.facts.length ? (
        <dl className="flex flex-col py-2">
          {reel.facts.map((f) => (
            <div
              key={f.label}
              data-row
              className={cn(ROW_HOVER_CLASS, "grid min-h-9 grid-cols-[8rem_minmax(0,1fr)] items-baseline gap-3 px-4 py-2 pointer-coarse:min-h-11")}
            >
              <dt data-layer="ui" className="text-ui text-muted-foreground">
                {f.label}
              </dt>
              <LayerValue layer="facts" as="dd" className="min-w-0">
                {f.value}
              </LayerValue>
            </div>
          ))}
        </dl>
      ) : (
        <p data-layer="ui" className="px-4 py-3 text-ui text-muted-foreground">
          {F.none}
        </p>
      )}
    </section>
  );
}
