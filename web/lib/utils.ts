// Class merging (clsx + tailwind-merge in one, the "cn" package). Our type scale adds text-ui
// (13px) and text-mono (12px) in app/globals.css; they are registered as font sizes here, or a
// colour class after them (text-muted-foreground) would drop them as if they were colours.
// Every component, the vendored shadcn ones included, imports cn from here.

import { createCn } from "cn/config";

export const cn = createCn({ extend: { classGroups: { "font-size": [{ text: ["ui", "mono"] }] } } });
