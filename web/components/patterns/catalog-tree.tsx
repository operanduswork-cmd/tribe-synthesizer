// The pattern catalog (Steep metrics catalog reference): All, then Hooks / Structures / CTAs /
// Formats in their fixed order, each with its pattern count right-aligned. A list on the left
// from 1024px; below that one row of 44px chips that scrolls sideways inside itself, so the
// pattern rows start higher on a phone. The count is how many patterns sit in a group, never a
// sort key. No visible "Catalog" heading (round 3 text cut); the nav keeps it as its name.

import { LayerValue } from "@/components/shared/layer-value";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

import type { KindFilter, PatternTab } from "./types";

type CatalogTreeProps = {
  tabs: PatternTab[];
  total: number;
  value: KindFilter;
  onChange: (value: KindFilter) => void;
  className?: string;
};

export function CatalogTree({ tabs, total, value, onChange, className }: CatalogTreeProps) {
  const items: Array<{ key: KindFilter; label: string; n: number; fresh: number }> = [
    { key: "all", label: copy.patterns.catalog.all, n: total, fresh: 0 },
    ...tabs.map((t) => ({ key: t.key, label: t.label, n: t.n, fresh: t.new })),
  ];
  return (
    <nav data-layer="ui" data-catalog aria-label={copy.patterns.catalog.label} className={cn("flex flex-col gap-2", className)}>
      <ul className="flex gap-2 overflow-x-auto [scrollbar-width:none] lg:flex-col lg:gap-0.5 lg:overflow-visible">
        {items.map((item) => {
          const active = value === item.key;
          return (
            <li key={item.key} className={cn("shrink-0", item.key !== "all" && "lg:pl-3")}>
              <button
                type="button"
                data-kind={item.key}
                aria-pressed={active}
                onClick={() => onChange(item.key)}
                className={cn(
                  "flex h-9 items-center gap-2 rounded-md border px-3 text-ui whitespace-nowrap pointer-coarse:h-11 lg:w-full lg:border-transparent lg:px-2",
                  active ? "border-line bg-subtle font-medium text-foreground" : "border-line text-muted-foreground hover:bg-subtle/60 hover:text-foreground",
                  item.n === 0 && !active && "opacity-60",
                )}
              >
                <span className="min-w-0 flex-1 truncate text-left">{item.label}</span>
                {item.fresh > 0 ? (
                  <span className="font-mono text-[10px] leading-4 text-muted-foreground">{fmt(copy.patterns.catalog.new, { n: item.fresh })}</span>
                ) : null}
                <LayerValue layer="ui" className="font-sans text-muted-foreground tabular-nums">
                  {item.n}
                </LayerValue>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
