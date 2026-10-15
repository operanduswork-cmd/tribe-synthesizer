// One shown value with its layer. Every rendered value carries data-layer, and the layer sets
// how it is drawn (the D20 wall stays visible): counts solid sans with tabular numbers, facts
// Geist Mono, shape as a chip (use ShapeChip), brain dotted, ui plain.

import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";

import type { Layer } from "@/lib/contract";
import { cn } from "@/lib/utils";

export type { Layer };

export const LAYER_CLASS: Record<Layer, string> = {
  counts: "font-sans tabular-nums",
  facts: "font-mono text-mono",
  shape: "",
  brain: "",
  ui: "",
};

type LayerValueProps<T extends ElementType> = {
  layer: Layer;
  /** The element to render (span by default). */
  as?: T;
  children: ReactNode;
  className?: string;
  /** Brain text gets a dotted underline unless this is "plain" (e.g. a label inside a dotted chart). */
  encoding?: "text" | "plain";
} & Omit<ComponentPropsWithoutRef<T>, "children" | "className" | "as">;

export function LayerValue<T extends ElementType = "span">({
  layer,
  as,
  children,
  className,
  encoding = "text",
  ...rest
}: LayerValueProps<T>) {
  const Tag = (as ?? "span") as ElementType;
  return (
    <Tag
      data-layer={layer}
      data-encoding={layer === "brain" ? encoding : undefined}
      className={cn(LAYER_CLASS[layer], className)}
      {...rest}
    >
      {children}
    </Tag>
  );
}
