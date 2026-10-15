// Loads the reels for the command palette. Pages and actions are always there,
// so a failed read still leaves a working palette.

import { CommandPalette } from "@/components/shell/command-palette";
import { getPaletteItems } from "@/lib/data";

export async function PaletteLoader() {
  const entries = await getPaletteItems().catch(() => []);
  return <CommandPalette entries={entries.filter((e) => e.group === "reels")} />;
}
