"use client";

// A page that failed to load, or failed its contract check (lib/hosted.ts): nothing from it is
// shown, only a retry.

import { EmptyState } from "@/components/shared/empty-state";
import { Button } from "@/components/ui/button";
import { copy } from "@/lib/copy";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <EmptyState
      title={copy.errors.refused}
      action={
        <Button variant="outline" size="sm" onClick={reset}>
          {copy.errors.retry}
        </Button>
      }
    />
  );
}
