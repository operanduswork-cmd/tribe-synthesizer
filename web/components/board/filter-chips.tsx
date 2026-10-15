"use client";

// The active filters as chips (Reddit Ads reference): "Hook = cold open question ×", with
// "+ Add filter" and "Clear" on the same line. A plain chip per field, never a query builder.
// Each value leads with its layer's colour dot (Linear's label chips: dot + ink text in an
// outlined pill), and a new chip fades in. The TRIBE chip sits in its own group behind a dotted
// rule, so a counts value and a brain value never share a line (D20).

import { PlusIcon, XIcon } from "lucide-react";

import { FilterMenu, filterValueLabel } from "@/components/board/board-toolbar";
import { FILTER_FIELDS, FILTER_LAYER, type Board, type FilterField, type Filters } from "@/components/board/model";
import { LayerDot } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { Button } from "@/components/ui/button";
import { copy, fmt } from "@/lib/copy";

const c = copy.board.filters;

function Chip({ board, field, filters, onChange }: { board: Board; field: FilterField; filters: Filters; onChange: (f: Filters) => void }) {
  const remove = () => {
    const next = { ...filters };
    delete next[field];
    onChange(next);
  };
  const layer = FILTER_LAYER[field];
  return (
    <span
      data-filter-chip={field}
      className="inline-flex h-7 max-w-full animate-appear items-center gap-1 rounded-md border border-line bg-surface pr-0.5 pl-2 text-ui pointer-coarse:h-11"
    >
      <span data-layer="ui" className="shrink-0 text-muted-foreground">
        {c.fields[field]}
      </span>
      <span data-layer="ui" aria-hidden className="shrink-0 font-mono text-mono text-muted-foreground">
        {c.eq}
      </span>
      {layer !== "ui" ? <LayerDot layer={layer} className={field === "tribe" ? "size-2.5" : "size-2"} /> : null}
      <LayerValue layer={layer} className="min-w-0 truncate font-medium">
        {filterValueLabel(board, field, filters)}
      </LayerValue>
      <Button
        variant="ghost"
        size="icon-xs"
        onClick={remove}
        aria-label={fmt(c.remove, { field: c.fields[field] })}
        className="text-muted-foreground"
      >
        <XIcon aria-hidden />
      </Button>
    </span>
  );
}

export function FilterChips({ board, filters, onChange }: { board: Board; filters: Filters; onChange: (f: Filters) => void }) {
  const active = FILTER_FIELDS.filter((f) => filters[f] !== undefined);
  if (!active.length) return null;
  const main = active.filter((f) => f !== "tribe");
  const tribe = active.includes("tribe");

  return (
    <div role="group" aria-label={c.label} data-board="chips" className="flex flex-wrap items-center gap-1.5">
      {main.length ? (
        <div data-line="filters" className="flex min-w-0 flex-wrap items-center gap-1.5">
          {main.map((f) => (
            <Chip key={f} board={board} field={f} filters={filters} onChange={onChange} />
          ))}
        </div>
      ) : null}
      {tribe ? (
        <div data-line="filters-brain" className="flex items-center gap-1.5 border-l border-dotted border-muted-foreground/50 pl-1.5 first:border-l-0 first:pl-0">
          <Chip board={board} field="tribe" filters={filters} onChange={onChange} />
        </div>
      ) : null}
      <FilterMenu
        board={board}
        filters={filters}
        onChange={onChange}
        trigger={
          <Button variant="ghost" size="sm" className="h-7 text-muted-foreground">
            <PlusIcon aria-hidden />
            {c.add}
          </Button>
        }
      />
      <Button variant="ghost" size="sm" className="h-7 text-muted-foreground" onClick={() => onChange({})}>
        {c.clear}
      </Button>
    </div>
  );
}
