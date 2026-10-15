// The four lines' icons (Seeing, Hearing, Language, Attention network). The lines get icons, never
// their own hues: four line hues next to the layer hues cannot all be told apart (D28, palette
// check), so the colour stays for the brain's diverging scale alone.

import { EarIcon, EyeIcon, MessageSquareTextIcon, NetworkIcon, type LucideIcon } from "lucide-react";

import type { LineKey } from "@/components/reel/time";
import { cn } from "@/lib/utils";

export const LINE_ICONS: Record<LineKey, LucideIcon> = {
  seeing: EyeIcon,
  hearing: EarIcon,
  language: MessageSquareTextIcon,
  attention: NetworkIcon,
};

export function LineIcon({ line, className }: { line: LineKey; className?: string }) {
  const Icon = LINE_ICONS[line];
  return <Icon aria-hidden data-line-icon={line} className={cn("size-3.5 shrink-0", className)} />;
}
