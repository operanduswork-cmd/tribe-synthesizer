"use client";

// "This but…" and "Replace X with Y" (WRITER's rewrite popover): a small panel under the button
// with the change to ask for, the /script command it makes (copy it into Claude Code on the
// laptop, which works today) and the run button for the same job from the site (stage 2, shown
// disabled with its stage until the coach jobs are on).

import { useId, useState } from "react";

import { CopyCommand } from "@/components/shared/copy-command";
import { JobButton } from "@/components/shared/job-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cleanArg } from "@/components/lab/lab-text";
import { copy } from "@/lib/copy";
import { jobKindLabel } from "@/lib/job-kinds";

type ThisButProps = {
  mode: "this_but";
  draftId: string;
  /** The command up to the change, e.g. "/script <id> this but " (from the page). */
  command: string;
  variantId?: string;
};

type ReplaceProps = {
  mode: "replace";
  draftId: string;
  /** "/script <id> replace " (from the page). */
  command: string;
};

type RefinePopoverProps = (ThisButProps | ReplaceProps) & {
  variant?: "outline" | "ghost";
  size?: "sm" | "xs";
  align?: "start" | "end";
  className?: string;
};

export function RefinePopover(props: RefinePopoverProps) {
  const { mode, variant = "outline", size = "sm", align = "start", className } = props;
  const label = jobKindLabel(mode === "this_but" ? "coach.this_but" : "coach.replace");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant={variant} size={size} className={className}>
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align={align} className="w-[min(22rem,calc(100vw-2rem))] gap-3 rounded-xl p-3" data-layer="ui">
        {mode === "this_but" ? <ThisButBody {...props} label={label} /> : <ReplaceBody {...props} label={label} />}
      </PopoverContent>
    </Popover>
  );
}

function Head({ label, body }: { label: string; body: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-mono text-muted-foreground">{label}</span>
      <span className="text-[13px] leading-5 text-muted-foreground">{body}</span>
    </div>
  );
}

function ThisButBody({ draftId, command, variantId, label }: ThisButProps & { label: string }) {
  const id = useId();
  const [text, setText] = useState("");
  const change = cleanArg(text);
  return (
    <>
      <Head label={label} body={variantId ? copy.lab.refine.thisButVariantBody : copy.lab.refine.thisButBody} />
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <Input
        id={id}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={copy.lab.refine.thisButPlaceholder}
        autoComplete="off"
        maxLength={500}
        className="h-9 rounded-md text-[13px] leading-5 pointer-coarse:h-11"
      />
      <CopyCommand command={command + (change || copy.lab.refine.yourChange)} label={copy.lab.refine.command} />
      <div className="flex flex-col gap-1">
        <span className="text-[13px] leading-5 text-muted-foreground">{copy.lab.refine.fromSite}</span>
        <JobButton
          kind="coach.this_but"
          args={{ draft_id: draftId, text: change, ...(variantId ? { variant_id: variantId } : {}) }}
          label={label}
        />
      </div>
    </>
  );
}

function ReplaceBody({ draftId, command, label }: ReplaceProps & { label: string }) {
  const id = useId();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const a = cleanArg(from);
  const b = cleanArg(to);
  const field = "h-9 rounded-md text-[13px] leading-5 pointer-coarse:h-11";
  return (
    <>
      <Head label={label} body={copy.lab.refine.replaceBody} />
      <div className="grid grid-cols-1 gap-2">
        <label htmlFor={`${id}-a`} className="flex flex-col gap-1 text-[13px] leading-5 text-muted-foreground">
          {copy.lab.refine.replace}
          <Input
            id={`${id}-a`}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            placeholder={copy.lab.refine.replacePlaceholder}
            autoComplete="off"
            maxLength={500}
            className={field}
          />
        </label>
        <label htmlFor={`${id}-b`} className="flex flex-col gap-1 text-[13px] leading-5 text-muted-foreground">
          {copy.lab.refine.with}
          <Input
            id={`${id}-b`}
            value={to}
            onChange={(e) => setTo(e.target.value)}
            placeholder={copy.lab.refine.withPlaceholder}
            autoComplete="off"
            maxLength={500}
            className={field}
          />
        </label>
      </div>
      <CopyCommand
        command={`${command}"${a || copy.lab.refine.x}" ${copy.lab.refine.with} "${b || copy.lab.refine.y}"`}
        label={copy.lab.refine.command}
      />
      <div className="flex flex-col gap-1">
        <span className="text-[13px] leading-5 text-muted-foreground">{copy.lab.refine.fromSite}</span>
        <JobButton kind="coach.replace" args={{ draft_id: draftId, replace: a, with: b }} label={label} />
      </div>
    </>
  );
}
