"use client";

// What the brain and the lists point at together, kept apart from the selected second so a
// hover never re-renders the lanes: an HCP area (one side or both), a Yeo network's areas, or one
// of the four lines' areas. The Areas rows and the lane labels set it; the 3D map outlines it and
// greys the rest a little. Hovering the 3D map sets an area, and the Areas tab marks its row
// when the row is on screen (it never scrolls the list). A tap pins it (touch).
//
// One store for the page (only one reel page is ever open); the brain section clears it when
// it unmounts. A separate tiny store holds the pointer position for the floating card, so moving
// the mouse inside one area does not re-render the rows.

import { useSyncExternalStore } from "react";

import type { LineKey } from "@/components/reel/time";

export type Side = "left" | "right";

export type BrainFocus =
  | { kind: "area"; k: number; side: Side | null; from: "brain" | "list"; pinned: boolean }
  | { kind: "net"; n: number; from: "list"; pinned: boolean }
  | { kind: "line"; line: LineKey; from: "lane"; pinned: false };

/** The id the canvas (data-hover-area) and the Areas rows (data-area-id) share. */
export function focusId(f: BrainFocus | null): string {
  if (!f) return "";
  if (f.kind === "area") return `hcp-${f.k}`;
  if (f.kind === "net") return `net-${f.n}`;
  return `line-${f.line}`;
}

type Store<T> = { get: () => T; set: (v: T) => void; subscribe: (fn: () => void) => () => void };

function store<T>(initial: T): Store<T> {
  let value = initial;
  const fns = new Set<() => void>();
  return {
    get: () => value,
    set: (v) => {
      if (Object.is(v, value)) return;
      value = v;
      for (const fn of fns) fn();
    },
    subscribe: (fn) => {
      fns.add(fn);
      return () => fns.delete(fn);
    },
  };
}

const focus = store<BrainFocus | null>(null);
const pointer = store<{ x: number; y: number } | null>(null);

const same = (a: BrainFocus | null, b: BrainFocus | null) => JSON.stringify(a) === JSON.stringify(b);

export function getFocus(): BrainFocus | null {
  return focus.get();
}

export function setFocus(next: BrainFocus | null) {
  if (!same(focus.get(), next)) focus.set(next);
}

/** Point at a target unless it is already the focus (so a hover or focus never undoes a pin). */
export function touchFocus(next: BrainFocus) {
  if (focusId(focus.get()) === focusId(next)) return;
  setFocus(next);
}

/** Clear the focus only if it is still the one this caller set (hover out of a row, a lane). */
export function clearFocus(id?: string) {
  const cur = focus.get();
  if (!cur) return;
  if (id !== undefined && focusId(cur) !== id) return;
  if (cur.pinned && id !== undefined) return;
  focus.set(null);
}

export function useBrainFocus(): BrainFocus | null {
  return useSyncExternalStore(focus.subscribe, focus.get, () => null);
}

/** Subscribe outside React (the 3D canvas updates its uniforms without re-rendering). */
export const subscribeFocus = focus.subscribe;

export function setPointer(p: { x: number; y: number } | null) {
  const cur = pointer.get();
  if (p && cur && cur.x === p.x && cur.y === p.y) return;
  pointer.set(p);
}

export function useBrainPointer(): { x: number; y: number } | null {
  return useSyncExternalStore(pointer.subscribe, pointer.get, () => null);
}
