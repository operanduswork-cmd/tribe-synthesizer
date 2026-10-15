"use client";

// The left column's tabs (Grain reference: Summary / Chapters / Transcript becomes
// Card / Beats / Areas / Facts). The panels are rendered on the server and passed in. Areas shows
// only when the reel has a brain page of its own (D28); the page always opens on Card (D18).

import type { ReactNode } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { copy } from "@/lib/copy";

const TABS = ["card", "beats", "areas", "facts"] as const;
type Tab = (typeof TABS)[number];

export function ReelTabs({ panels }: { panels: Record<Exclude<Tab, "areas">, ReactNode> & { areas?: ReactNode } }) {
  const tabs = TABS.filter((tab) => panels[tab] !== undefined && panels[tab] !== null);
  return (
    <Tabs defaultValue="card" className="gap-4">
      <TabsList aria-label={copy.reel.tabs.label} data-layer="ui" className="w-full sm:w-fit">
        {tabs.map((tab) => (
          <TabsTrigger key={tab} value={tab} className="tap-target px-3 pointer-coarse:h-9">
            {copy.reel.tabs[tab]}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((tab) => (
        <TabsContent key={tab} value={tab} className="flex flex-col gap-4">
          {panels[tab]}
        </TabsContent>
      ))}
    </Tabs>
  );
}
