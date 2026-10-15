// Route crossfade: Next 16 keeps each route in its own <Activity> below the app shell, so the
// shell's <ViewTransition> alone never sees a route change. A root template puts one inside each
// route (globals.css sets the timing and turns it off under reduced motion).

import { ViewTransition, type ReactNode } from "react";

export default function Template({ children }: { children: ReactNode }) {
  return <ViewTransition>{children}</ViewTransition>;
}
