"use client";

// The refresh icon button in the top bar (Gumloop reference): re-reads the page's data.

import { RefreshCwIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Button } from "@/components/ui/button";
import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

export function RefreshButton() {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <Button
      type="button"
      variant="outline"
      size="icon-sm"
      aria-label={copy.topbar.refresh}
      title={copy.topbar.refresh}
      aria-busy={pending}
      onClick={() => start(() => router.refresh())}
      className="tap-target pointer-coarse:size-8 max-md:border-transparent max-md:bg-transparent max-md:dark:border-transparent max-md:dark:bg-transparent"
    >
      <RefreshCwIcon className={cn(pending && "animate-spin")} aria-hidden />
    </Button>
  );
}
