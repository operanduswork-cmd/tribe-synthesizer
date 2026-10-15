// The page title block (Gumloop Insights reference): title, one grey subtitle line, actions on
// the right. The 48px top bar above it carries the runner status and the refresh button.

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type PageHeaderProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  /** Buttons or toggles on the right (they wrap under the title on a phone). */
  actions?: ReactNode;
  /** Optional row under the subtitle, e.g. filter chips or a saved-view pill. */
  children?: ReactNode;
  className?: string;
};

export function PageHeader({ title, subtitle, actions, children, className }: PageHeaderProps) {
  return (
    <header data-layer="ui" className={cn("flex flex-col gap-3 pb-6", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {subtitle ? <p className="text-ui text-muted-foreground">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </header>
  );
}
