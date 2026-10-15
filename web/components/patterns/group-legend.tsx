// The one (i) about the two groups being compared (round 3 text cut: the legend card is gone).
// It sits in the list's key row, beside the "Outliers / Normal" swatches, and opens to: each
// group with its colour dot (the colour of its bars), its size when every compared pattern shares
// one, and its one-line definition (Pinterest puts an (i) beside each audience); then the page
// notes (the caveats), the population lines (who is counted, who is left out), the page's data
// line, and why the folded "seen only in normal reels" rows have no Recreate. Counts layer for
// the sizes and the population, ui for the rest; nothing from a deep read is ever on this page.

import { InfoHint } from "@/components/shared/info-hint";
import { LayerValue } from "@/components/shared/layer-value";
import { copy, fmt } from "@/lib/copy";

import { GroupDot } from "./compare-bars";

type GroupsHintProps = {
  outliersN: number | null;
  normalN: number | null;
  population: string[];
  notes: string[];
  className?: string;
};

function Group({ group, n }: { group: "o" | "m"; n: number | null }) {
  const L = copy.patterns.legend;
  return (
    <div data-group={group === "o" ? "outliers" : "normal"} className="flex flex-col gap-0.5">
      <span className="flex items-center gap-2 font-medium">
        <GroupDot group={group} className="size-2.5" />
        <span>{group === "o" ? L.outliers : L.normal}</span>
        {n !== null ? (
          <LayerValue layer="counts" className="font-normal text-muted-foreground">
            {fmt(L.n, { n })}
          </LayerValue>
        ) : null}
      </span>
      <span data-group-def className="text-muted-foreground">
        {group === "o" ? L.outliersDef : L.normalDef}
      </span>
    </div>
  );
}

export function GroupsHint({ outliersN, normalN, population, notes, className }: GroupsHintProps) {
  const P = copy.patterns;
  return (
    <InfoHint
      label={P.legend.more}
      side="bottom"
      align="end"
      className={className}
      contentClassName="w-80 max-h-(--radix-popover-content-available-height) overflow-y-auto"
    >
      <div data-groups-hint className="flex flex-col gap-3">
        <div className="flex flex-col gap-2">
          <Group group="o" n={outliersN} />
          <Group group="m" n={normalN} />
        </div>
        <ul className="flex flex-col gap-1.5 border-t border-line pt-3 text-muted-foreground">
          {notes.map((line, i) => (
            <li key={`n${i}`} data-row data-note>
              <LayerValue layer="ui">{line}</LayerValue>
            </li>
          ))}
          {population.map((line, i) => (
            <li key={`p${i}`} data-row data-population>
              <LayerValue layer="counts">{line}</LayerValue>
            </li>
          ))}
          <li data-row>
            <span>{P.about}</span>
          </li>
          <li data-row className="flex flex-col gap-0.5">
            <span className="font-medium text-foreground">{P.zero.title}</span>
            <span>{P.zero.body}</span>
          </li>
        </ul>
      </div>
    </InfoHint>
  );
}
