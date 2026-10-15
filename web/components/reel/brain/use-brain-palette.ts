"use client";

// The brain palette as the page's CSS shows it right now (light or dark): the tokens in
// app/globals.css, read from the root element, and read again when next-themes switches the
// class or the system scheme changes. The server render and the first client render use the
// light defaults (lut.ts), so nothing differs at hydration; the hook updates right after.

import { useSyncExternalStore } from "react";

import { DEFAULT_PALETTE, hexToRgb, type BrainPalette } from "./lut";

let cached: BrainPalette | null = null;
let cachedKey = "";

function read(): BrainPalette {
  if (typeof document === "undefined") return DEFAULT_PALETTE.light;
  const cs = getComputedStyle(document.documentElement);
  const get = (name: string) => cs.getPropertyValue(name).trim();
  const dark = document.documentElement.classList.contains("dark") || cs.colorScheme === "dark";
  const key = [get("--brain-cool"), get("--brain-warm"), get("--brain-near"), get("--text"), dark].join("|");
  if (cached && key === cachedKey) return cached;
  const base = dark ? DEFAULT_PALETTE.dark : DEFAULT_PALETTE.light;
  cached = {
    cool: hexToRgb(get("--brain-cool")) ?? base.cool,
    warm: hexToRgb(get("--brain-warm")) ?? base.warm,
    near: hexToRgb(get("--brain-near")) ?? base.near,
    ink: hexToRgb(get("--text")) ?? base.ink,
    dark,
  };
  cachedKey = key;
  return cached;
}

function subscribe(onChange: () => void): () => void {
  const root = document.documentElement;
  const mo = new MutationObserver(onChange);
  mo.observe(root, { attributes: true, attributeFilter: ["class", "style"] });
  const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
  mq?.addEventListener("change", onChange);
  return () => {
    mo.disconnect();
    mq?.removeEventListener("change", onChange);
  };
}

export function useBrainPalette(): BrainPalette {
  return useSyncExternalStore(subscribe, read, () => DEFAULT_PALETTE.light);
}
