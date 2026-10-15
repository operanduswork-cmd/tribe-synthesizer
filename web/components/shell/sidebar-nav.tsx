"use client";

// The sidebar's nav list (Vercel overview and Linear references, Mintlify for the accent): 36px
// rows (44px on touch). Hover and the current page share a grey fill and ink text; the current
// page adds the one accent, indigo (selection, never a layer or a status): its icon and a 2px rail
// on the sidebar's edge. The rail carries a view-transition name, so on a route change it glides
// from the old row to the new one (instant under reduced motion; globals.css).

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV } from "@/components/shell/nav";
import { cn } from "@/lib/utils";

export function NavList({ activePath }: { activePath: string | null }) {
  return (
    <ul className="flex flex-col gap-0.5">
      {NAV.map((item) => {
        const active = activePath !== null && item.match(activePath);
        const Icon = item.icon;
        return (
          <li key={item.href}>
            <Link
              href={item.href}
              aria-current={active ? "page" : undefined}
              data-layer="ui"
              className={cn(
                "group/nav relative flex h-9 items-center gap-2.5 rounded-md px-2 text-ui text-muted-foreground pointer-coarse:h-11",
                "transition-colors duration-(--motion-fast) ease-(--motion-ease) hover:bg-subtle hover:text-foreground",
                active && "bg-subtle font-medium text-foreground shadow-[inset_0_0_0_1px_var(--surface-edge)]",
              )}
            >
              {active ? (
                <span
                  aria-hidden
                  data-nav-rail
                  className="absolute top-1/2 -left-3 h-4 w-0.5 -translate-y-1/2 rounded-r-full bg-indigo-accent [view-transition-name:shell-nav-rail]"
                />
              ) : null}
              <Icon
                aria-hidden
                className={cn(
                  "size-4 shrink-0 transition-colors duration-(--motion-fast)",
                  active ? "text-indigo-accent" : "group-hover/nav:text-foreground",
                )}
              />
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function SidebarNav() {
  return <NavList activePath={usePathname()} />;
}
