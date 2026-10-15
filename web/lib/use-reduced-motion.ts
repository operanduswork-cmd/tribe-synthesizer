"use client";

// prefers-reduced-motion for JavaScript motion (the brain's between-second blend, Reset tweens,
// smooth scrolls). CSS motion is turned off by the global block in app/globals.css. The server
// render and the first client render say false; the hook updates once the media query is read.

import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

const query = (): MediaQueryList | null => (typeof window === "undefined" || !window.matchMedia ? null : window.matchMedia(QUERY));

function subscribe(onChange: () => void): () => void {
  const mq = query();
  if (!mq) return () => {};
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

/** Read it once, now (for event handlers and callbacks that run outside React render). */
export function prefersReducedMotion(): boolean {
  return query()?.matches ?? false;
}

/** True while the viewer asks for reduced motion; follows changes live. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false);
}
