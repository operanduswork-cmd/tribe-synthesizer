"use client";

// The board screen's interactive part: toolbar, filter chips, the table (laptop) or cards
// (phone, or the grid view), and the peek panel. No footnote, stamp or "Page built" line (D30):
// the counts note sits behind the (i) next to the page title. The page data comes in
// already checked against the hosted schema (lib/data.ts); nothing here fetches.
//
// Filters and the sort live in this component (a saved view resets both). The layout and the
// shown columns are per-viewer conveniences kept in this browser (use-board-prefs).

import { useCallback, useMemo, useState } from "react";

import { BoardCards } from "@/components/board/board-cards";
import { BoardTable } from "@/components/board/board-table";
import { BoardToolbar } from "@/components/board/board-toolbar";
import { FilterChips } from "@/components/board/filter-chips";
import {
  creatorItems,
  currentView,
  matches,
  sortReels,
  sortSpec,
  viewState,
  type Board,
  type ColumnState,
  type Filters,
  type SortKey,
  type ViewId,
  type ViewState,
} from "@/components/board/model";
import { ReelPeek } from "@/components/board/reel-peek";
import { useBoardPrefs, type Layout } from "@/components/board/use-board-prefs";
import { EmptyState } from "@/components/shared/empty-state";
import { Button } from "@/components/ui/button";
import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

const c = copy.board;

export function BoardView({ board }: { board: Board }) {
  const [prefs, savePrefs] = useBoardPrefs();
  const [state, setState] = useState<ViewState>(() => viewState(board, "all"));
  const [peek, setPeek] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);

  const spec = sortSpec(board, state.sort);
  const shown = useMemo(
    () => sortReels(board.reels.filter((r) => matches(r, state.filters)), spec, state.pin),
    [board.reels, state.filters, spec, state.pin],
  );
  const view = currentView(board, state);
  const peekIndex = peek ? shown.findIndex((r) => r.sc === peek) : -1;
  const peekReel = peekIndex >= 0 ? shown[peekIndex] : null;

  const onView = (id: ViewId) => setState(viewState(board, id));
  const onFilters = (filters: Filters) => setState((s) => ({ ...s, filters }));
  const onSort = (sort: SortKey) => setState((s) => ({ ...s, sort, pin: false }));
  const onLayout = (layout: Layout) => savePrefs({ ...prefs, layout });
  const onColumns = (columns: ColumnState) => savePrefs({ ...prefs, columns: { ...columns, handle: true } });

  const closePeek = useCallback(() => setPeek(null), []);
  const move = useCallback(
    (step: -1 | 1) => {
      if (peekIndex < 0) return;
      const next = shown[peekIndex + step];
      if (next) setPeek(next.sc);
    },
    [peekIndex, shown],
  );

  return (
    <div data-board="view" className="page-wash flex flex-col gap-3">
      <BoardToolbar
        board={board}
        view={view}
        onView={onView}
        layout={prefs.layout}
        onLayout={onLayout}
        filters={state.filters}
        onFilters={onFilters}
        columns={prefs.columns}
        onColumns={onColumns}
        sort={spec}
        onSort={onSort}
        shown={shown.length}
        total={board.reels.length}
      />
      <FilterChips board={board} filters={state.filters} onChange={onFilters} />

      {shown.length === 0 ? (
        <EmptyState
          title={c.empty.noMatch}
          action={
            <Button variant="outline" size="sm" onClick={() => onView("all")}>
              {c.views.all}
            </Button>
          }
        />
      ) : (
        <>
          <div className={cn("hidden", prefs.layout === "table" && "md:block")}>
            <BoardTable
              board={board}
              reels={shown}
              columns={prefs.columns}
              sort={spec}
              onSort={onSort}
              selected={peek}
              hovered={hovered}
              onHover={setHovered}
              onPeek={setPeek}
            />
          </div>
          <BoardCards reels={shown} columns={prefs.columns} selected={peek} onPeek={setPeek} className={cn(prefs.layout === "table" && "md:hidden")} />
        </>
      )}

      <ReelPeek
        reel={peekReel}
        baseline={peekReel ? creatorItems(board, peekReel.handle) : []}
        onClose={closePeek}
        onMove={move}
        canPrev={peekIndex > 0}
        canNext={peekIndex >= 0 && peekIndex < shown.length - 1}
      />
    </div>
  );
}
