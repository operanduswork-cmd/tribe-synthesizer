"use client";

// The board toolbar. Order from the references: the saved-view pill first (Dovetail), a thin
// divider, then the table / cards toggle, Filters and Fields (Neon tables), the sort menu, and on
// the right the number of reels shown (Neon's "N rows", sliding in when it changes). The shell's
// top bar right above holds the refresh button, so it is not repeated here.
//
// Colour per category (Linear's label dots, Attio's typed headers): each field in the Filters
// menu leads with its layer's dot, the same dot as the column header tags. Text stays ink.
//
// Sort offers only the page's own sort keys (board.sorts); no TRIBE field is ever offered. The
// default order (read reels first, then longest clip) is a pin, not a key; picking any key drops it (D32).
// The sort button's arrow shows the direction. No explanation notes in the menus (D30).

import {
  ArrowDownWideNarrowIcon,
  ArrowUpDownIcon,
  ArrowUpNarrowWideIcon,
  CheckIcon,
  ChevronDownIcon,
  Columns3Icon,
  LayoutGridIcon,
  ListFilterIcon,
  Table2Icon,
} from "lucide-react";
import type { ReactNode } from "react";

import { LayerDot, LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  FILTER_FIELDS,
  FILTER_LAYER,
  TOGGLABLE,
  VIEW_IDS,
  defaultColumns,
  sortOptions,
  type Board,
  type ColumnId,
  type ColumnState,
  type FilterField,
  type Filters,
  type SortKey,
  type SortSpec,
  type ViewId,
} from "@/components/board/model";
import type { Layout } from "@/components/board/use-board-prefs";
import type { Layer } from "@/lib/contract";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

const c = copy.board;

const MENU = "w-auto min-w-48 text-ui";
const ITEM = "text-ui pointer-coarse:min-h-11";

// ---------------------------------------------------------------- filters menu

type FilterOption = { value: string; label: string };

/** The values each filter field can take, from the page's own options. */
export function filterOptions(board: Board, field: FilterField): FilterOption[] {
  switch (field) {
    case "hook":
      return board.options.hook.map((v) => ({ value: v, label: v }));
    case "format":
      return board.options.format.map((v) => ({ value: v, label: v }));
    case "length":
      return board.options.length.map((v) => ({ value: v, label: v }));
    case "flag":
      return board.options.flags.map((f) => ({ value: f.key, label: f.label }));
    case "twoX":
      return [{ value: "true", label: c.filters.twoX }];
    case "labels":
      return [{ value: "suggested", label: c.filters.suggested }];
    case "tribe":
      return [
        { value: "yes", label: c.filters.yes },
        { value: "no", label: c.filters.no },
      ];
  }
}

/** The shown label of a filter's current value. */
export function filterValueLabel(board: Board, field: FilterField, filters: Filters): string {
  const v = filters[field];
  if (v === undefined) return "";
  return filterOptions(board, field).find((o) => o.value === String(v))?.label ?? String(v);
}

export function setFilter(filters: Filters, field: FilterField, value: string): Filters {
  const next: Filters = { ...filters };
  if (field === "twoX") next.twoX = true;
  else if (field === "labels") next.labels = "suggested";
  else if (field === "tribe") next.tribe = value === "yes" ? "yes" : "no";
  else if (field === "flag") next.flag = value as Filters["flag"];
  else next[field] = value;
  return next;
}

/** The Filters menu: one submenu per field, the TRIBE field last behind a separator. */
export function FilterMenu({
  board,
  filters,
  onChange,
  trigger,
  align = "start",
}: {
  board: Board;
  filters: Filters;
  onChange: (f: Filters) => void;
  trigger: ReactNode;
  align?: "start" | "end";
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent align={align} className={MENU}>
        <DropdownMenuLabel className="text-mono text-muted-foreground">{c.filters.add}</DropdownMenuLabel>
        {FILTER_FIELDS.map((field) => {
          const opts = filterOptions(board, field);
          const current = filters[field] === undefined ? "" : String(filters[field]);
          return (
            <div key={field} data-filter-field={field}>
              {field === "tribe" ? <DropdownMenuSeparator /> : null}
              <DropdownMenuSub>
                <DropdownMenuSubTrigger className={ITEM}>
                  {FILTER_LAYER[field] !== "ui" ? (
                    <LayerDot layer={FILTER_LAYER[field] as Exclude<Layer, "ui">} className={field === "tribe" ? "size-2.5" : "size-2"} />
                  ) : null}
                  <span className="flex-1">{c.filters.fields[field]}</span>
                  {current ? <CheckIcon className="size-3.5 text-muted-foreground" aria-hidden /> : null}
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent className={MENU}>
                  {opts.length === 0 ? (
                    <DropdownMenuItem disabled className={ITEM}>
                      {c.filters.empty}
                    </DropdownMenuItem>
                  ) : (
                    <DropdownMenuRadioGroup value={current} onValueChange={(v) => onChange(setFilter(filters, field, v))}>
                      {opts.map((o) => (
                        <DropdownMenuRadioItem key={o.value} value={o.value} className={ITEM}>
                          <LayerValue layer={FILTER_LAYER[field]} encoding="plain" className="truncate">
                            {o.label}
                          </LayerValue>
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuRadioGroup>
                  )}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            </div>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// ---------------------------------------------------------------- toolbar

type ToolbarProps = {
  board: Board;
  view: ViewId | null;
  onView: (id: ViewId) => void;
  layout: Layout;
  onLayout: (l: Layout) => void;
  filters: Filters;
  onFilters: (f: Filters) => void;
  columns: ColumnState;
  onColumns: (cols: ColumnState) => void;
  sort: SortSpec | undefined;
  onSort: (key: SortKey) => void;
  shown: number;
  total: number;
};

export function BoardToolbar(p: ToolbarProps) {
  const active = FILTER_FIELDS.filter((f) => p.filters[f] !== undefined).length;
  const count =
    p.shown === p.total
      ? p.total === 1
        ? c.countOne
        : fmt(c.count, { n: p.total })
      : fmt(c.countOf, { shown: p.shown, total: p.total });

  return (
    <div role="toolbar" aria-label={c.controls} data-layer="ui" data-board="toolbar" className="flex flex-wrap items-center gap-2">
      {/* Saved view pill (Dovetail). */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            aria-label={c.views.label}
            data-board="view-pill"
            className="h-8 border-indigo-accent/40 bg-indigo-soft text-indigo-accent hover:bg-indigo-soft hover:text-indigo-accent pointer-coarse:h-11"
          >
            <span className="max-w-40 truncate">{p.view ? c.views[p.view] : c.views.custom}</span>
            <ChevronDownIcon aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className={MENU}>
          <DropdownMenuLabel className="text-mono text-muted-foreground">{c.views.menu}</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={p.view ?? ""} onValueChange={(v) => p.onView(v as ViewId)}>
            {VIEW_IDS.map((id) => (
              <DropdownMenuRadioItem key={id} value={id} className={ITEM}>
                {c.views[id]}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      <span aria-hidden data-board="toolbar-divider" className="mx-0.5 hidden h-5 w-px bg-line md:block" />

      {/* Table / cards (Neon). Phones always get cards, so the toggle is hidden there. */}
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={0}
        value={p.layout}
        onValueChange={(v) => v && p.onLayout(v as Layout)}
        aria-label={c.layout.label}
        className="hidden md:flex"
      >
        <ToggleGroupItem value="table" aria-label={c.layout.table} title={c.layout.table} className="h-8 w-9">
          <Table2Icon aria-hidden />
        </ToggleGroupItem>
        <ToggleGroupItem value="grid" aria-label={c.layout.grid} title={c.layout.grid} className="h-8 w-9">
          <LayoutGridIcon aria-hidden />
        </ToggleGroupItem>
      </ToggleGroup>

      <FilterMenu
        board={p.board}
        filters={p.filters}
        onChange={p.onFilters}
        trigger={
          <Button variant="outline" size="sm" className="h-8 pointer-coarse:h-11" data-board="filters">
            <ListFilterIcon aria-hidden />
            <span>{c.filters.button}</span>
            {active ? (
              <span
                key={active}
                className="ml-0.5 inline-flex h-4 min-w-4 animate-appear items-center justify-center rounded-sm bg-foreground px-1 font-mono text-[10px] text-background tabular-nums"
              >
                {active}
              </span>
            ) : null}
          </Button>
        }
      />

      <FieldsPopover columns={p.columns} onColumns={p.onColumns} />

      <SortMenu board={p.board} sort={p.sort} onSort={p.onSort} />

      <span data-board="count" className="ml-auto font-mono text-mono whitespace-nowrap text-muted-foreground tabular-nums">
        <span key={count} className="readout-in inline-block">
          {count}
        </span>
      </span>
    </div>
  );
}

// ---------------------------------------------------------------- fields (Dovetail)

function FieldsPopover({ columns, onColumns }: { columns: ColumnState; onColumns: (cols: ColumnState) => void }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 pointer-coarse:h-11" data-board="fields" aria-label={c.fields.button}>
          <Columns3Icon aria-hidden />
          <span className="hidden sm:inline">{c.fields.button}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 gap-1 p-1.5" data-board="fields-popover">
        <div className="flex items-center justify-between px-1.5 pt-1">
          <span className="text-ui font-medium">{c.fields.title}</span>
          <Button variant="ghost" size="xs" onClick={() => onColumns(defaultColumns())}>
            {c.fields.reset}
          </Button>
        </div>
        <ul className="flex flex-col">
          {TOGGLABLE.map((col) => {
            const id = `board-field-${col.id}`;
            return (
              <li key={col.id} className="flex h-9 items-center gap-2 rounded-md px-1.5 hover:bg-subtle pointer-coarse:h-11">
                <label htmlFor={id} className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-ui">
                  <span className="truncate">{c.columns[col.id as ColumnId]}</span>
                  {col.layer !== "ui" ? <LayerTag layer={col.layer} /> : null}
                </label>
                <Switch
                  id={id}
                  size="sm"
                  checked={columns[col.id]}
                  onCheckedChange={(on) => onColumns({ ...columns, [col.id]: on })}
                  data-column={col.id}
                />
              </li>
            );
          })}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

// ---------------------------------------------------------------- sort

function SortMenu({ board, sort, onSort }: { board: Board; sort: SortSpec | undefined; onSort: (key: SortKey) => void }) {
  const opts = sortOptions(board);
  const Icon = !sort ? ArrowUpDownIcon : sort.desc ? ArrowDownWideNarrowIcon : ArrowUpNarrowWideIcon;
  // The button says "Sort" only; the current sort is in its name and hover text, the arrow and
  // the checked menu item (D30, less text).
  const name = sort ? fmt(c.sort.label, { label: sort.label }) : c.sort.button;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-8 max-w-full pointer-coarse:h-11"
          data-board="sort"
          aria-label={name}
          title={name}
        >
          <Icon aria-hidden data-sort-dir={sort ? (sort.desc ? "desc" : "asc") : undefined} />
          <span className="hidden sm:inline">{c.sort.button}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className={cn(MENU, "max-w-72")} data-board="sort-menu">
        <DropdownMenuLabel className="text-mono text-muted-foreground">{c.sort.menu}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={sort?.key ?? ""} onValueChange={(v) => onSort(v as SortKey)}>
          {opts.map((s) => (
            <DropdownMenuRadioItem key={s.key} value={s.key} className={ITEM} data-sort-key={s.key}>
              {s.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
