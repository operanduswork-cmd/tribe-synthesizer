"use client";

// Discount a reel's counts by hand, with a reason (reel.discount, a free job). Nothing is ever
// discounted automatically (D19); the reason is one line, checked again by zod and the runner.

import { useState, useTransition, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { copy } from "@/lib/copy";
import { JOB_KIND_SPECS } from "@/lib/job-kinds";
import { enqueueJob } from "@/lib/jobs";

const D = copy.reel.discount;
const MAX = Number(JOB_KIND_SPECS.find((k) => k.kind === "reel.discount")?.args.properties.reason?.maxLength ?? 200);

export function DiscountForm({ sc }: { sc: string }) {
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [pending, start] = useTransition();

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = reason.replace(/\s+/g, " ").trim();
    if (!text) {
      setMessage(D.empty);
      return;
    }
    start(async () => {
      const r = await enqueueJob("reel.discount", { sc, reason: text });
      setMessage(r.message);
    });
  }

  return (
    <Popover onOpenChange={(open) => !open && setMessage("")}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="xs" data-job-kind="reel.discount">
          {D.open}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 max-w-[calc(100vw-2rem)]" data-layer="ui">
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h3 className="text-sm font-medium">{D.title}</h3>
            <p className="text-ui text-muted-foreground">{D.body}</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`discount-${sc}`} className="text-ui">
              {D.reason}
            </Label>
            <Input
              id={`discount-${sc}`}
              value={reason}
              maxLength={MAX}
              placeholder={D.placeholder}
              autoComplete="off"
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <div className="flex items-center justify-end gap-2">
            <Button type="submit" size="sm" disabled={pending} aria-busy={pending}>
              {pending ? copy.jobs.working : D.send}
            </Button>
          </div>
          <p role="status" aria-live="polite" className="text-ui text-muted-foreground empty:hidden">
            {message}
          </p>
        </form>
      </PopoverContent>
    </Popover>
  );
}
