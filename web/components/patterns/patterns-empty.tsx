// No patterns yet (Copilot reference): one short line with the reel count so far, and the one
// laptop command that gets there (round 3 text cut: no body, no numbered steps). Under 10 reels
// that is bringing reels in; from 10 on it is building the patterns.

import { ShapesIcon } from "lucide-react";

import { CopyCommand } from "@/components/shared/copy-command";
import { EmptyState } from "@/components/shared/empty-state";
import { copy } from "@/lib/copy";

/** The plan's first-run line: "compare once 10 reels are in (3/10)". */
const REELS_TO_COMPARE = 10;

export function PatternsEmpty({ reels }: { reels: number }) {
  const E = copy.patterns.empty;
  return (
    <EmptyState
      icon={<ShapesIcon />}
      title={E.title}
      progress={{ done: Math.min(reels, REELS_TO_COMPARE), total: REELS_TO_COMPARE }}
      action={<CopyCommand command={reels < REELS_TO_COMPARE ? E.importCommand : E.buildCommand} label={null} />}
    />
  );
}
