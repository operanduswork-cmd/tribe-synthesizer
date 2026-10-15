"use client";

// The phone tab bar under 768px (Edits reference): the four nav items plus Find (five tabs), 44px targets.
// The current tab: ink label, indigo icon and a short indigo rail on the bar's top edge (indigo is
// selection, never a layer or a status). The rail glides between tabs on a route change through
// its view-transition name; a pressed icon dips slightly (both instant under reduced motion).

import { SearchIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV, openPalette } from "@/components/shell/nav";
import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

const icon = "size-5 transition-transform duration-(--motion-fast) ease-(--motion-ease) group-active/tab:scale-90";

export function TabList({ activePath }: { activePath: string | null }) {
  const cell =
    "group/tab relative flex h-14 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 text-ui transition-colors duration-(--motion-fast)";
  return (
    <ul className="flex items-stretch">
      {NAV.map((item) => {
        const active = activePath !== null && item.match(activePath);
        const Icon = item.icon;
        return (
          <li key={item.href} className="flex flex-1">
            <Link
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(cell, active ? "font-medium text-foreground" : "text-muted-foreground")}
            >
              {active ? (
                <span
                  aria-hidden
                  data-nav-rail
                  className="absolute top-0 left-1/2 h-0.5 w-6 -translate-x-1/2 rounded-b-full bg-indigo-accent [view-transition-name:shell-tab-rail]"
                />
              ) : null}
              <Icon aria-hidden className={cn(icon, active && "stroke-[2.25] text-indigo-accent")} />
              <span className="truncate">{item.label}</span>
            </Link>
          </li>
        );
      })}
      <li className="flex flex-1">
        <button type="button" onClick={openPalette} className={cn(cell, "text-muted-foreground")}>
          <SearchIcon aria-hidden className={icon} />
          <span>{copy.palette.title}</span>
        </button>
      </li>
    </ul>
  );
}

export function BottomTabs() {
  return <TabList activePath={usePathname()} />;
}
