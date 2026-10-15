// The app's name and its "private" chip: at the top of the sidebar, and in the phone top bar on
// the top-level pages (where the bar shows no page label, since the H1 already names the page).

import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

export function AppMark({ className }: { className?: string }) {
  return (
    <div data-layer="ui" data-app-mark className={cn("flex items-center gap-2", className)}>
      <span className="text-sm font-semibold tracking-tight">{copy.app.name}</span>
      <span className="rounded-sm border border-line px-1 font-mono text-[10px] leading-4 text-muted-foreground">
        {copy.app.private}
      </span>
    </div>
  );
}
