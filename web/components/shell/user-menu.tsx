"use client";

// The user menu at the foot of the sidebar (and in the phone top bar): theme switch and which
// data the site is showing (fixtures or live).

import { CircleUserIcon, MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { copy } from "@/lib/copy";
import type { DataSource } from "@/lib/env";
import { cn } from "@/lib/utils";

const noop = () => () => {};

export function UserMenu({ source, compact = false }: { source: DataSource; compact?: boolean }) {
  const { theme, setTheme } = useTheme();
  // The saved theme is only known in the browser: show "system" until then.
  const mounted = useSyncExternalStore(noop, () => true, () => false);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-layer="ui"
        aria-label={copy.topbar.menu}
        className={cn(
          "flex items-center gap-2 rounded-md text-ui text-muted-foreground hover:bg-subtle hover:text-foreground",
          compact ? "size-8 justify-center tap-target" : "h-9 w-full px-2 pointer-coarse:h-11",
        )}
      >
        <CircleUserIcon className="size-4 shrink-0" aria-hidden />
        {compact ? null : <span className="flex-1 truncate text-left">{copy.menu.owner}</span>}
      </DropdownMenuTrigger>
      <DropdownMenuContent align={compact ? "end" : "start"} side={compact ? "bottom" : "top"} className="w-56">
        <DropdownMenuLabel className="text-muted-foreground">
          {source === "db" ? copy.menu.sourceDb : copy.menu.sourceFixtures}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{copy.menu.theme}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={mounted ? (theme ?? "system") : "system"} onValueChange={setTheme}>
          <DropdownMenuRadioItem value="light">
            <SunIcon aria-hidden />
            {copy.menu.light}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <MoonIcon aria-hidden />
            {copy.menu.dark}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <MonitorIcon aria-hidden />
            {copy.menu.system}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
