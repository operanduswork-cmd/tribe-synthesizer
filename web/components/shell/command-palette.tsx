"use client";

// The command palette (Magnific reference): search on top, grouped rows with a key hint on the
// right, a footer of key hints. Opens with Cmd/Ctrl+K, with F outside a text field, and from the
// Find box or the phone tab bar (openPalette). Built from the dialog parts rather than
// CommandDialog, so the screen-reader title and description sit inside the dialog content: closed,
// the palette leaves no hidden text on the page.

import { FilmIcon, MonitorIcon, MoonIcon, RefreshCwIcon, SunIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { NAV, PALETTE_EVENT } from "@/components/shell/nav";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { copy } from "@/lib/copy";

export type PaletteEntry = { group: "reels" | "drafts"; label: string; detail: string; href: string };

const typing = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

export function CommandPalette({ entries = [] }: { entries?: PaletteEntry[] }) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { setTheme } = useTheme();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (!e.metaKey && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === "f" && !typing(e.target)) {
        e.preventDefault();
        setOpen(true);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(PALETTE_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(PALETTE_EVENT, onOpen);
    };
  }, []);

  function go(href: string) {
    setOpen(false);
    router.push(href);
  }

  function run(action: () => void) {
    setOpen(false);
    action();
  }

  const reels = entries.filter((e) => e.group === "reels");

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="top-1/3 translate-y-0 overflow-hidden rounded-xl! p-0 shadow-lg sm:max-w-xl" showCloseButton={false}>
        <DialogHeader className="sr-only">
          <DialogTitle>{copy.palette.title}</DialogTitle>
          <DialogDescription>{copy.palette.description}</DialogDescription>
        </DialogHeader>
        <Command>
          <CommandInput placeholder={copy.palette.placeholder} />
          <CommandList data-layer="ui" className="[&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:uppercase">
            <CommandEmpty>{copy.palette.empty}</CommandEmpty>
            <CommandGroup heading={copy.palette.groups.pages}>
              {NAV.map((item) => (
                <CommandItem key={item.href} value={`page ${item.label}`} onSelect={() => go(item.href)}>
                  <item.icon aria-hidden />
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
            {reels.length ? (
              <CommandGroup heading={copy.palette.groups.reels}>
                {reels.map((e) => (
                  <CommandItem key={e.href} value={`reel ${e.label} ${e.detail}`} onSelect={() => go(e.href)}>
                    <FilmIcon aria-hidden />
                    <span className="truncate">{e.label}</span>
                    <CommandShortcut className="font-mono tracking-normal">{e.detail}</CommandShortcut>
                  </CommandItem>
                ))}
              </CommandGroup>
            ) : null}
            <CommandGroup heading={copy.palette.groups.actions}>
              <CommandItem value="action refresh" onSelect={() => run(() => router.refresh())}>
                <RefreshCwIcon aria-hidden />
                {copy.palette.actions.refresh}
              </CommandItem>
              <CommandItem value="action theme light" onSelect={() => run(() => setTheme("light"))}>
                <SunIcon aria-hidden />
                {copy.palette.actions.light}
              </CommandItem>
              <CommandItem value="action theme dark" onSelect={() => run(() => setTheme("dark"))}>
                <MoonIcon aria-hidden />
                {copy.palette.actions.dark}
              </CommandItem>
              <CommandItem value="action theme system" onSelect={() => run(() => setTheme("system"))}>
                <MonitorIcon aria-hidden />
                {copy.palette.actions.system}
              </CommandItem>
            </CommandGroup>
          </CommandList>
          <div data-layer="ui" className="flex items-center gap-4 border-t border-line px-3 py-2 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <kbd className="font-mono">{copy.palette.keys.navigate}</kbd>
              {copy.palette.hints.navigate}
            </span>
            <span className="flex items-center gap-1.5">
              <kbd className="font-mono">{copy.palette.keys.open}</kbd>
              {copy.palette.hints.open}
            </span>
            <span className="flex items-center gap-1.5">
              <kbd className="font-mono">{copy.palette.keys.close}</kbd>
              {copy.palette.hints.close}
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
