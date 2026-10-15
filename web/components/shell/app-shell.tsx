// The app shell (Vercel project overview reference, Linear dark): a 232px sidebar with Find, the
// nav and one small freshness line ("Data · 9 Oct", its (i) opens to one line per layer), a 48px
// top bar with the page title, the runner status and a refresh button, the one-line licence
// footer (its (i) holds the full text) under every page, and under 768px the freshness line as a
// strip under the top bar and a bottom tab bar.
// Everything that reads data sits in <Suspense> (Cache Components).
// Route changes crossfade (React <ViewTransition>; globals.css sets the timing and turns it off under
// reduced motion). The top bar and the phone tab bar carry their own view-transition names, so the
// fading page never paints over them, and the nav rails glide between rows (sidebar-nav, bottom-tabs).

import { Suspense, ViewTransition, type ReactNode } from "react";

import { BottomTabs, TabList } from "@/components/shell/bottom-tabs";
import { FindButton } from "@/components/shell/find-button";
import { AppMark } from "@/components/shell/app-mark";
import { Freshness, FreshnessLine } from "@/components/shell/freshness";
import { LicenceFooter } from "@/components/shell/licence-footer";
import { PaletteLoader } from "@/components/shell/palette-loader";
import { RefreshButton } from "@/components/shell/refresh-button";
import { RunnerStatus } from "@/components/shell/runner-status";
import { NavList, SidebarNav } from "@/components/shell/sidebar-nav";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { TopBarTitle } from "@/components/shell/top-bar-title";
import { UserMenu } from "@/components/shell/user-menu";
import { copy } from "@/lib/copy";
import { dataSource } from "@/lib/env";

export function AppShell({ children }: { children: ReactNode }) {
  const source = dataSource();
  return (
    <div className="flex min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-surface px-3 py-2 text-ui focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        {copy.app.skip}
      </a>

      <aside
        data-layer="ui"
        data-shell="sidebar"
        className="sticky top-0 hidden h-dvh w-sidebar shrink-0 flex-col gap-3 border-r border-line bg-sidebar bg-gradient-to-b from-[var(--surface-glow)] to-transparent to-30% px-3 py-3 md:flex"
      >
        <AppMark className="h-6 px-2" />
        <FindButton />
        <nav aria-label={copy.nav.label} className="flex-1">
          <Suspense fallback={<NavList activePath={null} />}>
            <SidebarNav />
          </Suspense>
        </nav>
        <Suspense fallback={<div className="mx-2 h-6 rounded-sm bg-subtle" />}>
          <Freshness className="px-2" />
        </Suspense>
        <UserMenu source={source} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          data-layer="ui"
          data-shell="topbar"
          className="sticky top-0 z-30 flex h-topbar shrink-0 items-center gap-3 border-b border-line bg-canvas/95 px-4 shadow-[0_1px_0_0_var(--surface-glow)] backdrop-blur [view-transition-name:shell-topbar] md:px-6"
        >
          <div className="flex min-w-0 flex-1 flex-col justify-center">
            <Suspense fallback={<AppMark className="md:hidden" />}>
              <TopBarTitle />
            </Suspense>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Suspense fallback={null}>
              <RunnerStatus className="hidden min-[375px]:inline-flex" />
              <RunnerStatus compact className="min-[375px]:hidden" />
            </Suspense>
            <RefreshButton />
            <ThemeToggle />
            <div className="md:hidden">
              <UserMenu source={source} compact />
            </div>
          </div>
        </header>

        <div data-layer="ui" className="border-b border-line px-4 md:hidden">
          <Suspense fallback={<div className="h-9 pointer-coarse:h-11" />}>
            <FreshnessLine />
          </Suspense>
        </div>

        <main id="main" className="flex-1 px-4 py-6 md:px-6">
          {/* Unnamed: Suspense reveals crossfade; nothing is morphed between pages. A route change
              needs the boundary inside each route (app/template.tsx), since a layout persists. */}
          <ViewTransition>{children}</ViewTransition>
        </main>
        <div className="pb-[calc(var(--shell-tabbar)+env(safe-area-inset-bottom))] md:pb-0">
          <LicenceFooter />
        </div>
      </div>

      <nav
        aria-label={copy.nav.label}
        data-layer="ui"
        data-shell="tabbar"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-canvas/95 pb-[env(safe-area-inset-bottom)] backdrop-blur [view-transition-name:shell-tabbar] md:hidden"
      >
        <Suspense fallback={<TabList activePath={null} />}>
          <BottomTabs />
        </Suspense>
      </nav>

      <Suspense fallback={null}>
        <PaletteLoader />
      </Suspense>
    </div>
  );
}
