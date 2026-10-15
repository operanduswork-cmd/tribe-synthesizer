// Render a copy template with {slots} filled by elements, e.g. the licence footer's links.

import { Fragment, type ReactNode } from "react";

import { slots } from "@/lib/copy";

export function Rich({ template, parts }: { template: string; parts: Record<string, ReactNode> }) {
  return (
    <>
      {slots(template).map((s, i) => (
        <Fragment key={i}>{"text" in s ? s.text : (parts[s.slot] ?? null)}</Fragment>
      ))}
    </>
  );
}
