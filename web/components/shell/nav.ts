// The four nav items and the top bar breadcrumb for each route. Nav labels come
// from copy; the screens own their routes (app/<route>/**).

import { DownloadIcon, LayoutGridIcon, SettingsIcon, ShapesIcon, type LucideIcon } from "lucide-react";

import { copy } from "@/lib/copy";

export type NavItem = { href: string; label: string; icon: LucideIcon; match: (path: string) => boolean };

export const NAV: NavItem[] = [
  { href: "/board", label: copy.nav.board, icon: LayoutGridIcon, match: (p) => p === "/" || p.startsWith("/board") || p.startsWith("/reels") },
  { href: "/patterns", label: copy.nav.patterns, icon: ShapesIcon, match: (p) => p.startsWith("/patterns") },
  { href: "/export", label: copy.nav.export, icon: DownloadIcon, match: (p) => p.startsWith("/export") },
  { href: "/settings/jobs", label: copy.nav.settings, icon: SettingsIcon, match: (p) => p.startsWith("/settings") },
];

/** One step of the top bar breadcrumb. A parent with an href links back; the last step is the page. */
export type Crumb = { label: string; href?: string; mono?: boolean };

/** The top bar breadcrumb for a path (Linear reference): the trail sits in the top bar, so the
 *  page's own title shows once, in its H1. A detail page (a reel) has a linked parent. */
export function crumbsFor(path: string): Crumb[] {
  const reel = /^\/reels\/([^/]+)/.exec(path);
  if (reel) return [{ label: copy.nav.board, href: "/board" }, { label: reel[1], mono: true }];
  // Settings has one section (/settings redirects here), so its step does not link.
  if (path.startsWith("/settings/jobs")) return [{ label: copy.nav.settings }, { label: copy.nav.jobs }];
  return [{ label: NAV.find((n) => n.match(path))?.label ?? copy.app.name }];
}

/** Opens the command palette from anywhere (the Find box, the phone tab bar). */
export const PALETTE_EVENT = "tribe:palette";

export function openPalette() {
  window.dispatchEvent(new Event(PALETTE_EVENT));
}
