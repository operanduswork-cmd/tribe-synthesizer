// The board: other creators' reels with their public counts, facts and shapes (D19). The header
// renders at once; the data part sits in <Suspense> (Cache Components) and reads through
// lib/data.ts, which checks the page against the hosted schema first.
//
// References: Neon tables (toolbar, layer tags in the headers), Reddit Ads (filter chips),
// Dovetail (saved-view pill, Fields popover), Twenty (420px peek), Binance Data Center (phone
// cards). Never a rank number, a sort on a TRIBE field, or a brain value in the peek. The TRIBE
// column says yes or no only (D21).
//
// Round 3 (D30, less text): no subtitle, stamp or "Page built" line. The one page note (counts
// are snapshots) sits behind the (i) next to the title, not inside the h1 (Plain reporting).

import type { Metadata } from "next";
import { Suspense } from "react";

import { BoardView } from "@/components/board/board-view";
import { Creators } from "@/components/board/creators";
import { CopyCommand } from "@/components/shared/copy-command";
import { EmptyState } from "@/components/shared/empty-state";
import { InfoHint } from "@/components/shared/info-hint";
import { PageSkeleton } from "@/components/shared/page-skeleton";
import { copy, fmt } from "@/lib/copy";
import { getBoard } from "@/lib/data";

export const metadata: Metadata = { title: copy.pages.board.title };

export default function BoardPage() {
  const title = copy.pages.board.title;
  return (
    <>
      <header data-layer="ui" data-board="header" className="flex items-center gap-2 pb-4">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <InfoHint label={fmt(copy.ui.hintAbout, { topic: title })} side="bottom" align="start">
          {copy.board.footnote}
        </InfoHint>
      </header>
      <Suspense fallback={<PageSkeleton rows={6} />}>
        <BoardContent />
      </Suspense>
    </>
  );
}

async function BoardContent() {
  const board = await getBoard();
  const e = copy.board.empty;
  if (!board || board.reels.length === 0) {
    return (
      <EmptyState
        title={e.title}
        action={
          <div className="flex items-center gap-2">
            <CopyCommand command={e.addCommand} label={null} className="min-w-0 flex-1" />
            <InfoHint label={fmt(copy.ui.hintAbout, { topic: e.title })} side="top" align="end">
              {e.hint}
            </InfoHint>
          </div>
        }
      />
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <BoardView board={board} />
      <Creators board={board} />
    </div>
  );
}
