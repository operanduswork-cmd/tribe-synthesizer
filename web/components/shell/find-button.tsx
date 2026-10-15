"use client";

// The "Find… F" box at the top of the sidebar (Vercel reference). It opens the command palette;
// so do F (outside a text field) and Cmd/Ctrl+K.

import { SearchIcon } from "lucide-react";

import { openPalette } from "@/components/shell/nav";
import { copy } from "@/lib/copy";

export function FindButton() {
  return (
    <button
      type="button"
      onClick={openPalette}
      data-layer="ui"
      aria-keyshortcuts="F Control+K Meta+K"
      className="flex h-8 w-full items-center gap-2 rounded-md border border-line bg-surface px-2 text-ui text-muted-foreground transition-colors hover:text-foreground pointer-coarse:h-11"
    >
      <SearchIcon className="size-4 shrink-0" aria-hidden />
      <span className="flex-1 text-left">{copy.nav.find}</span>
      <kbd className="rounded-sm border border-line px-1 font-mono text-[10px] leading-4">{copy.nav.findKey}</kbd>
    </button>
  );
}
