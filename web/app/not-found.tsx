import Link from "next/link";

import { EmptyState } from "@/components/shared/empty-state";
import { Button } from "@/components/ui/button";
import { copy } from "@/lib/copy";

export default function NotFound() {
  return (
    <EmptyState
      title={copy.errors.notFound}
      action={
        <Button asChild variant="outline" size="sm">
          <Link href="/board">{copy.errors.back}</Link>
        </Button>
      }
    />
  );
}
