"use client";

// One-click light/dark switch in the top bar. The icon follows the .dark class on <html> through
// CSS (sun in dark, moon in light), so it is right before hydration with no flash or shift. The
// name and the click use the resolved theme, known only in the browser, so until then the label is
// the neutral "Theme". The account menu keeps its Light / Dark / System radio.

import { MoonIcon, SunIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { copy } from "@/lib/copy";

const noop = () => () => {};

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(noop, () => true, () => false);
  const dark = resolvedTheme === "dark";
  // The name says what a click does: in dark it offers Light, in light it offers Dark.
  const label = !mounted ? copy.menu.theme : dark ? copy.menu.light : copy.menu.dark;

  return (
    <Button
      type="button"
      variant="outline"
      size="icon-sm"
      data-theme-toggle
      aria-label={label}
      title={label}
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="tap-target pointer-coarse:size-8 max-md:border-transparent max-md:bg-transparent max-md:dark:border-transparent max-md:dark:bg-transparent"
    >
      <SunIcon className="hidden dark:block" aria-hidden />
      <MoonIcon className="dark:hidden" aria-hidden />
    </Button>
  );
}
