"use client";

// The breadcrumb in the 48px top bar, from the current route (Linear reference): parents link
// back, the last step is the page itself and truncates. A top-level page (Board, Patterns, Script
// lab, Settings) names itself once, in its H1, so the bar shows no page label there; on a phone it
// shows the app mark instead, since the sidebar is hidden. A detail page (a reel, a draft) keeps
// its trail, and on a phone shows only a back link to its parent.

import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { AppMark } from "@/components/shell/app-mark";
import { crumbsFor } from "@/components/shell/nav";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

export function TopBarTitle() {
  const crumbs = crumbsFor(usePathname());
  // Only a detail page has a step that links back; anything else is a top-level page.
  if (!crumbs.some((c) => c.href)) return <AppMark className="md:hidden" />;
  const parent = crumbs.length > 1 ? crumbs[crumbs.length - 2] : undefined;
  const back = parent?.href ? { href: parent.href, label: parent.label } : null;

  return (
    <nav aria-label={copy.nav.crumbs} data-layer="ui" data-crumbs className="flex min-w-0 items-center">
      {back ? (
        <Link
          href={back.href}
          className="-ml-2 inline-flex h-11 min-w-0 items-center gap-1 rounded-md px-2 text-ui font-medium text-muted-foreground transition-colors duration-(--motion-fast) hover:text-foreground md:hidden"
        >
          <ChevronLeftIcon aria-hidden className="size-4 shrink-0" />
          <span className="truncate">{fmt(copy.topbar.back, { page: back.label })}</span>
        </Link>
      ) : null}
      <ol className={cn("min-w-0 items-center gap-1 text-ui", back ? "hidden md:flex" : "flex")}>
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <li key={`${i}-${c.label}`} className={cn("flex items-center gap-1", last ? "min-w-0" : "shrink-0")}>
              {i > 0 ? <ChevronRightIcon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" /> : null}
              {c.href && !last ? (
                <Link
                  href={c.href}
                  className="tap-target flex min-w-0 rounded-sm text-muted-foreground transition-colors duration-(--motion-fast) hover:text-foreground"
                >
                  <span className="truncate">{c.label}</span>
                </Link>
              ) : (
                <span
                  aria-current={last ? "page" : undefined}
                  className={cn("truncate", last ? "font-medium" : "text-muted-foreground", c.mono && "font-mono text-mono")}
                >
                  {c.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
