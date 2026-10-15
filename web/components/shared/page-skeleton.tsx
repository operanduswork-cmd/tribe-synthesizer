// The loading shape for a page's data (the Suspense fallback): a few grey 36px rows.

import { Skeleton } from "@/components/ui/skeleton";
import { copy } from "@/lib/copy";

export function PageSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div data-layer="ui" aria-busy className="flex flex-col gap-2">
      <span className="sr-only">{copy.loading}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full rounded-md" />
      ))}
    </div>
  );
}
