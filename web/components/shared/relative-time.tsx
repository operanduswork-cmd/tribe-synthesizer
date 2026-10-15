"use client";

// A time shown as "3 min ago" once the page is in the browser, and as a fixed UTC time before
// that (server render), so the server never reads the clock and hydration always matches.

import { useSyncExternalStore } from "react";

import { ago } from "@/lib/copy";
import { formatUtc } from "@/lib/format";

const STEP_MS = 30_000;

function subscribe(onChange: () => void) {
  const id = window.setInterval(onChange, STEP_MS);
  return () => window.clearInterval(id);
}
const clientTick = () => Math.floor(Date.now() / STEP_MS);
const serverTick = () => null;

export function RelativeTime({ iso, className }: { iso: string | null | undefined; className?: string }) {
  const tick = useSyncExternalStore(subscribe, clientTick, serverTick);
  if (!iso) return null;
  const text = tick === null ? formatUtc(iso) : ago(iso, new Date());
  return (
    <time dateTime={iso} title={formatUtc(iso)} className={className}>
      {text}
    </time>
  );
}
