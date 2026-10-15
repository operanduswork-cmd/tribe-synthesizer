"use client";

// Per-viewer board conveniences kept in this browser only: table or cards, and which columns
// show (the Fields popover). Read through useSyncExternalStore so the server render and the
// first client render agree (defaults), then the saved choice applies. Storage can be blocked
// (private window, cleared site data): every access is guarded and the page works without it.

import { useCallback, useMemo, useSyncExternalStore } from "react";

import { defaultColumns, type ColumnId, type ColumnState } from "@/components/board/model";

export type Layout = "table" | "grid";
export type BoardPrefs = { layout: Layout; columns: ColumnState };

const KEY = "tribe.board.prefs.v2";
const listeners = new Set<() => void>();
let memory: string | null = null;

function read(): string | null {
  if (memory !== null) return memory;
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function write(value: string) {
  memory = value;
  try {
    window.localStorage.setItem(KEY, value);
  } catch {
    // storage off: the choice lasts until the tab closes
  }
  for (const l of listeners) l();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function parse(raw: string | null): BoardPrefs {
  const prefs: BoardPrefs = { layout: "table", columns: defaultColumns() };
  if (!raw) return prefs;
  try {
    const v = JSON.parse(raw) as Partial<{ layout: unknown; columns: Record<string, unknown> }>;
    if (v.layout === "table" || v.layout === "grid") prefs.layout = v.layout;
    for (const id of Object.keys(prefs.columns) as ColumnId[]) {
      if (typeof v.columns?.[id] === "boolean") prefs.columns[id] = v.columns[id] as boolean;
    }
    prefs.columns.handle = true;
  } catch {
    // a broken value falls back to the defaults
  }
  return prefs;
}

export function useBoardPrefs(): [BoardPrefs, (next: BoardPrefs) => void] {
  const raw = useSyncExternalStore(subscribe, read, () => null);
  const prefs = useMemo(() => parse(raw), [raw]);
  const save = useCallback((next: BoardPrefs) => write(JSON.stringify(next)), []);
  return [prefs, save];
}
