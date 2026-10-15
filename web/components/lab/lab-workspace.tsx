"use client";

// The script lab (WRITER editor reference), three zones:
//   - the draft (~58%): one block per beat, with numbered ticks on its right edge for the margin
//     notes (Notion suggesting mode);
//   - a column of suggestion cards under Facts / Shape / Brain tabs, each tab with a 2px top rule
//     in its layer's colour (Grammarly review: the category bars stay coloured on every tab),
//     Accept / Dismiss on each card;
//   - a rail of checks: copy / voice / rules as a dot shape and a word (never a red or green
//     fill), then length against the target, words and pace (WRITER's stats).
// Explanations sit behind (i) hints instead of paragraphs (the Brain tab, the laptop row, the copy
// check, each beat's slot, each variant's family and why, the variants' order note, a PROOF
// row's caveat), so the page shows its parts, labels and values, not its instructions (round 3
// text cut).
// From 1024px the rail sits beside the draft (sticky); from 1280px all three sit side by side.
// Below 1280px there is no margin, so each margin note sits under its own beat instead of a tick,
// and the Facts tab holds only the PROOF rows.
// On a phone it is one column, the checks first with their details folded.
//
// The copy check shows only where a shared 6-word run sits in the draft (a dashed underline and
// "characters 11 to 47"), never the run's words or where they came from (D25). Dismiss hides a
// card in this browser only; nothing is written.

import { LaptopIcon, XIcon } from "lucide-react";
import { Tabs as TabsPrimitive } from "radix-ui";
import { useMemo, useState, type ReactNode } from "react";

import { LengthBar } from "@/components/lab/length-bar";
import { RefinePopover } from "@/components/lab/refine-popover";
import {
  beatIndex,
  splitBySpans,
  stripWhere,
  whereLabel,
  wordCount,
  type BadgeState,
  type Beat,
  type Hit,
  type Issue,
  type Variant,
} from "@/components/lab/lab-text";
import { CopyCommand } from "@/components/shared/copy-command";
import { InfoHint } from "@/components/shared/info-hint";
import { JobButton } from "@/components/shared/job-button";
import { LayerDot, LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { ShapeChip } from "@/components/shared/shape-chip";
import { StatusDot, type DotTone } from "@/components/shared/status-dot";
import { TimeChip } from "@/components/shared/time-chip";
import { Button } from "@/components/ui/button";
import { copy, fmt } from "@/lib/copy";
import type { LabPage } from "@/lib/hosted";
import { prefersReducedMotion } from "@/lib/use-reduced-motion";
import { cn } from "@/lib/utils";

type Tab = "facts" | "shape" | "brain";

const TABS: Tab[] = ["facts", "shape", "brain"];

// The 2px rule on each tab, in its layer's colour (half strength until the tab is open): facts
// ink, shape indigo (every card under it is a suggestion), brain dotted and split cool / warm like
// the BRAIN dot. The brain tab's own top border stays 2px but transparent, and BrainRule draws the
// two dotted halves over it.
const RULE: Record<Tab, string> = {
  facts: "border-t-facts/40 data-[state=active]:border-t-facts",
  shape: "border-t-shape/45 data-[state=active]:border-t-shape",
  brain: "border-dotted border-t-transparent",
};

const CHECK_TONE: Record<BadgeState, DotTone> = {
  ok: "solid",
  fix: "dashed",
  look: "hollow",
  unchecked: "muted",
  stale: "muted",
};

const CHECK_KEY: Record<string, "copy" | "voice" | "rules" | "length"> = {
  "Copy check": "copy",
  Voice: "voice",
  Rules: "rules",
  Length: "length",
};

const capsLabel = "font-mono text-mono text-muted-foreground";

export function LabWorkspace({ lab }: { lab: LabPage }) {
  const [tab, setTab] = useState<Tab>("facts");
  const [activeNote, setActiveNote] = useState<number | null>(null);
  const [hiddenNotes, setHiddenNotes] = useState<number[]>([]);
  const [hiddenVariants, setHiddenVariants] = useState<string[]>([]);
  const [flashBeat, setFlashBeat] = useState<number | null>(null);
  const [checkDetails, setCheckDetails] = useState(false);

  const spans = useMemo(() => {
    const byBeat = new Map<number, Array<[number, number]>>();
    for (const h of lab.hits) {
      const i = h.kind === "copy" && h.span && h.where.endsWith(".say") ? beatIndex(h.where) : null;
      if (i !== null && h.span) byBeat.set(i, [...(byBeat.get(i) ?? []), h.span]);
    }
    return byBeat;
  }, [lab.hits]);
  const words = useMemo(() => lab.beats.reduce((n, b) => n + wordCount(b.say), 0), [lab.beats]);
  const notes = lab.beats.flatMap((b, i) => b.notes.map((n) => ({ ...n, beat: i, chip: b.chip })));
  const hookAt = lab.beats.findIndex((b) => b.kind === "hook");
  const hookSay = hookAt >= 0 ? lab.beats[hookAt].say : "";

  function scrollTo(id: string, block: ScrollLogicalPosition = "nearest") {
    const behavior: ScrollBehavior = prefersReducedMotion() ? "auto" : "smooth";
    window.requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block, behavior }));
  }
  function goNote(n: number) {
    setTab("facts");
    setActiveNote(n);
    scrollTo(`lab-note-${n}`);
  }
  function goVariants() {
    setTab("shape");
    scrollTo("lab-variants");
  }
  function showBeat(i: number) {
    setFlashBeat(i);
    scrollTo(`lab-beat-${i}`, "center");
    window.setTimeout(() => setFlashBeat((b) => (b === i ? null : b)), 1600);
  }

  const counts: Record<Tab, number> = {
    facts: notes.length - hiddenNotes.length + lab.proof.length,
    shape: lab.variants.length - hiddenVariants.length + lab.patterns.length,
    brain: 0,
  };

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_15rem] xl:grid-cols-[minmax(0,58fr)_minmax(0,24fr)_minmax(0,18fr)]">
      {/* ------------------------------------------------------------ the draft */}
      <section data-lab-zone="draft" data-layer="ui" aria-label={copy.lab.draft.label} className="flex min-w-0 flex-col gap-4 lg:col-start-1 lg:row-start-1">
        <div className="flex flex-col overflow-hidden rounded-xl border border-line bg-surface">
          <div className="flex h-10 items-center justify-between gap-3 border-b border-line px-4">
            <span className="text-[13px] leading-5 font-medium">{copy.lab.draft.label}</span>
            <LayerValue layer="facts" className="truncate text-muted-foreground">
              {fmt(copy.lab.draft.summary, { beats: lab.beats.length, words })}
            </LayerValue>
          </div>
          {lab.beats.length ? (
            <ol className="flex flex-col divide-y divide-line">
              {lab.beats.map((b, i) => (
                <BeatBlock
                  key={i}
                  beat={b}
                  index={i}
                  spans={spans.get(i) ?? []}
                  flash={flashBeat === i}
                  activeNote={activeNote}
                  onTick={goNote}
                  variants={i === hookAt ? lab.variants.length : 0}
                  onVariants={goVariants}
                  hiddenNotes={hiddenNotes}
                  onDismiss={(n) => setHiddenNotes((h) => [...h, n])}
                />
              ))}
            </ol>
          ) : (
            <p className="px-4 py-6 text-[13px] leading-5 text-muted-foreground">{copy.lab.draft.noBeats}</p>
          )}
          {hiddenNotes.length ? (
            <div className="border-t border-line px-4 py-2 xl:hidden">
              <Restore n={hiddenNotes.length} onRestore={() => setHiddenNotes([])} />
            </div>
          ) : null}
        </div>
        {/* Vercel "start with one command" row: the private page, with the shared runs and their
            sources, is opened on the laptop. A laptop mark and the command; what it holds sits
            behind the (i). */}
        <div data-layer="ui" data-lab-laptop className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2.5">
          <LaptopIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
          <CopyCommand command={lab.commands.render} label={null} className="min-w-0 flex-1 sm:max-w-[26rem]" />
          <InfoHint label={copy.lab.hints.laptop} side="top" align="end">
            {copy.lab.laptop.body}
          </InfoHint>
        </div>
      </section>

      {/* ------------------------------------------------------------ suggestions */}
      <section
        data-lab-zone="suggestions"
        data-layer="ui"
        aria-label={copy.lab.tabs.label}
        className="min-w-0 lg:col-start-1 lg:row-start-2 xl:col-start-2 xl:row-start-1"
      >
        <TabsPrimitive.Root
          value={tab}
          onValueChange={(v) => setTab(v as Tab)}
          className="flex flex-col overflow-hidden rounded-xl border border-line bg-surface"
        >
          <TabsPrimitive.List aria-label={copy.lab.tabs.label} className="grid grid-cols-3 border-b border-line">
            {TABS.map((t) => (
              <TabsPrimitive.Trigger
                key={t}
                value={t}
                data-tab-layer={t}
                className={cn(
                  "group relative flex h-10 items-center justify-center gap-1.5 border-t-2 text-[13px] leading-5 text-muted-foreground transition-colors hover:text-foreground pointer-coarse:h-11",
                  "data-[state=active]:bg-subtle data-[state=active]:font-medium data-[state=active]:text-foreground",
                  RULE[t],
                )}
              >
                {t === "brain" ? <BrainRule /> : null}
                <span>{copy.lab.tabs[t]}</span>
                {t === "facts" ? (
                  <>
                    {/* Below 1280px the margin notes sit under their beats, so Facts holds only the PROOF rows. */}
                    <span className="font-mono text-[12px] leading-4 tabular-nums opacity-70 xl:hidden">{lab.proof.length}</span>
                    <span className="hidden font-mono text-[12px] leading-4 tabular-nums opacity-70 xl:inline">{counts.facts}</span>
                  </>
                ) : (
                  <span className="font-mono text-[12px] leading-4 tabular-nums opacity-70">{counts[t]}</span>
                )}
              </TabsPrimitive.Trigger>
            ))}
          </TabsPrimitive.List>

          <TabsPrimitive.Content value="facts" className="flex flex-col gap-5 p-3 outline-none data-[state=active]:animate-appear">
            <Group title={copy.lab.notes.title} className="hidden xl:flex">
              {notes.length ? (
                <ol className="flex flex-col gap-2">
                  {notes
                    .filter((n) => !hiddenNotes.includes(n.n))
                    .map((n) => (
                      <li
                        key={n.n}
                        id={`lab-note-${n.n}`}
                        data-row
                        data-note={n.n}
                        data-active={activeNote === n.n || undefined}
                        onMouseEnter={() => setActiveNote(n.n)}
                        onFocus={() => setActiveNote(n.n)}
                        className={cn(
                          "flex scroll-mt-20 flex-col gap-2 rounded-md border border-line p-2.5 transition-colors",
                          activeNote === n.n && "border-indigo-accent",
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <NoteNumber n={n.n} active={activeNote === n.n} />
                          {/* The beat's time chip says where the note sits; "beat 3" only when it has none. */}
                          {n.chip ? (
                            <TimeChip time={n.chip} onClick={() => showBeat(n.beat)} />
                          ) : (
                            <LayerValue layer="ui" className="min-w-0 truncate font-mono text-[12px] leading-4 text-muted-foreground">
                              {whereLabel(`beats[${n.beat}]`)}
                            </LayerValue>
                          )}
                          <DismissNote className="ml-auto" onDismiss={() => setHiddenNotes((h) => [...h, n.n])} />
                        </div>
                        <LayerValue as="p" layer="ui" className="text-[13px] leading-5">
                          {n.text}
                        </LayerValue>
                      </li>
                    ))}
                </ol>
              ) : (
                <Empty>{copy.lab.notes.empty}</Empty>
              )}
              {hiddenNotes.length ? <Restore n={hiddenNotes.length} onRestore={() => setHiddenNotes([])} /> : null}
            </Group>
            <Group title={copy.lab.proof.title}>
              {lab.proof.length ? (
                <ul className="flex flex-col gap-2">
                  {lab.proof.map((p, i) => (
                    <li key={i} data-row className="flex flex-col gap-0.5 text-[13px] leading-5">
                      <span className="flex min-w-0 items-baseline gap-2">
                        <LayerValue layer="ui" className="shrink-0 font-mono text-[12px] leading-4">
                          {p.row}
                        </LayerValue>
                        <LayerValue layer="ui" className="min-w-0 flex-1">
                          {p.fact}
                        </LayerValue>
                        {/* The row's caveat sits behind its (i). */}
                        {p.caveat ? (
                          <InfoHint label={copy.lab.hints.caveat} side="bottom" align="end" className="self-center">
                            {fmt(copy.lab.proof.caveat, { caveat: p.caveat })}
                          </InfoHint>
                        ) : null}
                      </span>
                      <LayerValue layer="ui" className="text-[12px] leading-4 text-muted-foreground">
                        {fmt(copy.lab.proof.numbers, { numbers: p.numbers })}
                      </LayerValue>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>{copy.lab.proof.empty}</Empty>
              )}
            </Group>
          </TabsPrimitive.Content>

          <TabsPrimitive.Content value="shape" className="flex flex-col gap-5 p-3 outline-none data-[state=active]:animate-appear">
            <Group
              title={copy.lab.variants.title}
              hint={
                <InfoHint label={copy.lab.hints.variants} side="bottom" align="start">
                  {copy.lab.variants.unordered}
                </InfoHint>
              }
              id="lab-variants"
            >
              {lab.variants.length ? (
                <ul className="flex flex-col gap-2">
                  {lab.variants
                    .filter((v) => !hiddenVariants.includes(v.id))
                    .map((v) => (
                      <VariantCard
                        key={v.id}
                        variant={v}
                        draftId={lab.id}
                        hookSay={hookSay}
                        onDismiss={() => setHiddenVariants((h) => [...h, v.id])}
                      />
                    ))}
                </ul>
              ) : (
                <Empty>{copy.lab.variants.empty}</Empty>
              )}
              {hiddenVariants.length ? <Restore n={hiddenVariants.length} onRestore={() => setHiddenVariants([])} /> : null}
            </Group>
            <Group title={copy.lab.patterns.title}>
              {lab.patterns.length ? (
                <ul className="flex flex-col gap-2">
                  {lab.patterns.map((p) => (
                    <li key={p.id} data-row className="flex flex-col gap-1 text-[13px] leading-5">
                      <span className="flex items-center gap-2">
                        <LayerValue layer="ui" className="font-medium">
                          {p.kind}
                        </LayerValue>
                        <LayerTag layer="counts" />
                      </span>
                      <LayerValue layer="counts" className="text-muted-foreground">
                        {p.line}
                      </LayerValue>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>{copy.lab.patterns.empty}</Empty>
              )}
            </Group>
          </TabsPrimitive.Content>

          {/* No read on drafts: the split BRAIN mark, the title and a "Later" chip (Notion's empty
              states: a mark and one line); what the hook pair test would be sits behind the (i). */}
          <TabsPrimitive.Content value="brain" className="p-3 outline-none data-[state=active]:animate-appear">
            <div
              data-layer="ui"
              data-lab-brain
              className="flex items-center gap-3 rounded-md border border-dotted border-muted-foreground/50 p-3"
            >
              <LayerDot layer="brain" className="size-7 text-muted-foreground" />
              <div className="flex min-w-0 flex-1 flex-col items-start gap-1">
                <span className="flex items-center gap-1.5">
                  <span className="text-[13px] leading-5 font-medium">{copy.lab.brain.title}</span>
                  <InfoHint label={copy.lab.hints.brain} side="bottom" align="end">
                    <span className="flex flex-col gap-2">
                      <span>{copy.lab.brain.body}</span>
                      <span>{copy.lab.brain.note}</span>
                    </span>
                  </InfoHint>
                </span>
                <span className="inline-flex h-5 items-center rounded-sm border border-dotted border-muted-foreground/50 px-1.5 font-mono text-[12px] leading-4 text-muted-foreground">
                  {copy.lab.brain.later}
                </span>
              </div>
            </div>
          </TabsPrimitive.Content>
        </TabsPrimitive.Root>
      </section>

      {/* ------------------------------------------------------------ the checks rail */}
      <aside
        data-lab-zone="checks"
        data-layer="ui"
        aria-label={copy.lab.checks.title}
        className="order-first min-w-0 lg:sticky lg:top-16 lg:order-none lg:col-start-2 lg:row-span-2 lg:row-start-1 xl:col-start-3 xl:row-span-1"
      >
        <div className="flex flex-col overflow-hidden rounded-xl border border-line bg-surface">
          <div className="flex h-10 items-center justify-between gap-2 border-b border-line px-3">
            <span className="text-[13px] leading-5 font-medium">{copy.lab.checks.title}</span>
            <LayerValue
              layer="ui"
              title={lab.checked ? fmt(copy.lab.checks.checked, { date: lab.checked }) : undefined}
              className="truncate font-mono text-[12px] leading-4 text-muted-foreground"
            >
              {lab.checked ?? copy.lab.header.notChecked}
            </LayerValue>
          </div>
          <ul className="flex flex-col divide-y divide-line">
            {lab.badges
              .filter((b) => CHECK_KEY[b.name] !== "length")
              .map((b) => {
                const key = CHECK_KEY[b.name];
                const hasDetails = key === "copy" ? lab.hits.length > 0 : lab.issues.some((i) => i.check === key);
                return (
                  <CheckRow
                    key={b.name}
                    name={b.name}
                    state={b.state}
                    text={b.text}
                    check={key}
                    open={checkDetails}
                    hasDetails={hasDetails}
                    hint={
                      key === "copy" && lab.hits.length ? (
                        <InfoHint label={copy.lab.hints.private} side="bottom" align="start">
                          {copy.lab.checks.private}
                        </InfoHint>
                      ) : null
                    }
                  >
                    {key === "copy" ? (
                      <CopyHits hits={lab.hits} variants={lab.variants} onShow={showBeat} />
                    ) : (
                      <Issues issues={lab.issues.filter((i) => i.check === key)} variants={lab.variants} onShow={showBeat} />
                    )}
                  </CheckRow>
                );
              })}
          </ul>
          <LengthBlock lab={lab} words={words} open={checkDetails} />
          <div className="border-t border-line p-2 lg:hidden">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-expanded={checkDetails}
              onClick={() => setCheckDetails((o) => !o)}
              className="w-full pointer-coarse:h-11"
            >
              {checkDetails ? copy.lab.checks.hideDetails : copy.lab.checks.showDetails}
            </Button>
          </div>
        </div>
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------- the draft

type BeatBlockProps = {
  beat: Beat;
  index: number;
  spans: Array<[number, number]>;
  flash: boolean;
  activeNote: number | null;
  onTick: (n: number) => void;
  variants: number;
  onVariants: () => void;
  hiddenNotes: number[];
  onDismiss: (n: number) => void;
};

function BeatBlock({ beat, index, spans, flash, activeNote, onTick, variants, onVariants, hiddenNotes, onDismiss }: BeatBlockProps) {
  const parts = splitBySpans(beat.say, spans);
  const inlineNotes = beat.notes.filter((n) => !hiddenNotes.includes(n.n));
  return (
    <li
      id={`lab-beat-${index}`}
      data-row
      data-beat={index}
      className={cn("relative flex scroll-mt-20 flex-col gap-2 px-4 py-4 transition-colors duration-500 xl:pr-11", flash && "bg-indigo-soft")}
    >
      <div className="flex flex-wrap items-center gap-2">
        {beat.chip ? <TimeChip time={beat.chip} /> : null}
        <LayerValue layer="shape" className="inline-flex h-5 items-center rounded-sm border border-line bg-subtle px-1.5 font-mono text-[12px] leading-4">
          {beat.kind}
        </LayerValue>
        {beat.name && beat.name !== beat.kind ? (
          <LayerValue layer="shape" className="min-w-0 truncate text-[13px] leading-5 text-muted-foreground">
            {beat.name}
          </LayerValue>
        ) : null}
        {/* The shape's slot for this beat (what the line is there to do) sits behind its (i). */}
        {beat.slot ? (
          <InfoHint label={copy.lab.draft.slot} layer="shape" side="bottom" align="start">
            {beat.slot}
          </InfoHint>
        ) : null}
      </div>

      {beat.say ? (
        <p data-say={index} data-layer="ui" className="text-[15px] leading-7 text-pretty">
          {parts.map((p, i) =>
            p.hit ? (
              <span
                key={i}
                data-hit="copy"
                data-layer="ui"
                title={copy.lab.draft.sharedRun}
                className="underline decoration-foreground/60 decoration-dashed decoration-1 underline-offset-[6px]"
              >
                {p.text}
              </span>
            ) : (
              p.text
            ),
          )}
        </p>
      ) : (
        <p className="text-[13px] leading-5 text-muted-foreground italic">{copy.lab.draft.emptySay}</p>
      )}

      {beat.on_screen ? (
        <p className="flex flex-wrap items-baseline gap-x-2 text-[13px] leading-5">
          <span className={capsLabel}>{copy.lab.draft.onScreen}</span>
          <LayerValue layer="ui">{beat.on_screen}</LayerValue>
        </p>
      ) : null}
      {variants ? (
        <button
          type="button"
          onClick={onVariants}
          className="tap-target w-fit rounded-sm text-[13px] leading-5 text-indigo-accent underline decoration-indigo-accent/40 underline-offset-2 hover:decoration-indigo-accent"
        >
          {variants === 1 ? copy.lab.draft.variantsOne : fmt(copy.lab.draft.variantsMany, { n: variants })}
        </button>
      ) : null}

      {/* Below 1280px there is no margin beside the draft, so each note sits under its beat. */}
      {inlineNotes.length ? (
        <ol data-beat-notes className="flex flex-col gap-1.5 xl:hidden">
          {inlineNotes.map((n) => (
            <li key={n.n} data-note-inline={n.n} className="flex items-start gap-2 rounded-md border border-line p-2">
              <NoteNumber n={n.n} active={false} />
              <LayerValue as="p" layer="ui" className="min-w-0 flex-1 text-[13px] leading-5">
                {n.text}
              </LayerValue>
              <DismissNote onDismiss={() => onDismiss(n.n)} />
            </li>
          ))}
        </ol>
      ) : null}

      {beat.notes.length ? (
        <div className="absolute top-4 right-3 hidden flex-col gap-1.5 xl:flex">
          {beat.notes.map((n) => (
            <button
              key={n.n}
              type="button"
              data-tick={n.n}
              aria-label={fmt(copy.lab.draft.tick, { n: n.n })}
              onClick={() => onTick(n.n)}
              className={cn(
                "relative flex size-5 items-center justify-center rounded-full border font-mono text-mono tabular-nums transition-colors after:absolute after:-inset-2.5 tap-target",
                activeNote === n.n
                  ? "border-indigo-accent bg-indigo-soft text-indigo-accent"
                  : "border-line text-muted-foreground hover:border-foreground/40 hover:text-foreground",
              )}
            >
              {n.n}
            </button>
          ))}
        </div>
      ) : null}
    </li>
  );
}

// ---------------------------------------------------------------- suggestion cards

function VariantCard({ variant: v, draftId, hookSay, onDismiss }: { variant: Variant; draftId: string; hookSay: string; onDismiss: () => void }) {
  return (
    <li data-row data-hook-variant={v.id} className="flex flex-col gap-2 rounded-md border border-line p-2.5">
      {/* The chip and the line show; the shape's family and why this variant sit behind the (i). */}
      <div className="flex min-w-0 items-center gap-1.5">
        <ShapeChip label={v.shape} status="suggested" field={copy.lab.variants.field} className="min-w-0" />
        {v.family || v.why ? (
          <InfoHint label={copy.lab.hints.variant} side="bottom" align="end" className="ml-auto">
            <span className="flex flex-col gap-1">
              {v.family ? (
                <LayerValue layer="shape" className="text-muted-foreground">
                  {v.family}
                </LayerValue>
              ) : null}
              {v.why ? <LayerValue layer="ui">{v.why}</LayerValue> : null}
            </span>
          </InfoHint>
        ) : null}
      </div>
      <LayerValue as="p" layer="ui" className="text-[15px] leading-6 text-pretty">
        {v.line}
      </LayerValue>
      <p className="flex items-start gap-1.5">
        <LayerTag layer="counts" className="mt-0.5 shrink-0" />
        <LayerValue layer="counts" className="text-[12px] leading-5 text-muted-foreground">
          {v.pattern}
        </LayerValue>
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <JobButton
          kind="coach.replace"
          args={{ draft_id: draftId, replace: hookSay, with: v.line }}
          label={copy.lab.variants.accept}
          size="xs"
          variant="default"
        />
        <RefinePopover mode="this_but" draftId={draftId} command={v.cmd} variantId={v.id} size="xs" />
        <Button type="button" variant="ghost" size="xs" onClick={onDismiss}>
          {copy.lab.variants.dismiss}
        </Button>
      </div>
    </li>
  );
}

/** The Brain tab's 2px top rule: two dotted halves, cool then warm, drawn over the tab's own
 *  transparent top border (so the border keeps its 2px width). Half strength until the tab is
 *  open, like the other rules. Decorative. */
function BrainRule() {
  return (
    <span
      aria-hidden
      data-tab-rule="brain"
      className="pointer-events-none absolute inset-x-0 -top-0.5 flex opacity-50 transition-opacity group-data-[state=active]:opacity-100"
    >
      <span className="flex-1 border-t-2 border-dotted border-brain-cool" />
      <span className="flex-1 border-t-2 border-dotted border-brain-warm" />
    </span>
  );
}

function NoteNumber({ n, active }: { n: number; active: boolean }) {
  return (
    <span
      data-layer="ui"
      className={cn(
        "flex size-5 shrink-0 items-center justify-center rounded-full font-mono text-mono tabular-nums",
        active ? "bg-indigo-accent text-surface" : "bg-foreground text-surface",
      )}
    >
      {n}
    </span>
  );
}

/** Dismiss for a margin note, as an icon in the note's header row (Notion margin comments). */
function DismissNote({ onDismiss, className }: { onDismiss: () => void; className?: string }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      aria-label={copy.lab.notes.dismiss}
      title={copy.lab.notes.dismiss}
      className={cn("shrink-0 text-muted-foreground", className)}
      onClick={onDismiss}
    >
      <XIcon aria-hidden />
    </Button>
  );
}

/** A titled group in a suggestions tab. An optional (i) sits next to the title, never inside it. */
function Group({ title, hint, id, className, children }: { title: string; hint?: ReactNode; id?: string; className?: string; children: ReactNode }) {
  return (
    <div id={id} className={cn("flex scroll-mt-20 flex-col gap-2", className)}>
      <div className="flex items-center gap-1.5">
        <h3 className={capsLabel}>{title}</h3>
        {hint}
      </div>
      {children}
    </div>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-[13px] leading-5 text-muted-foreground">{children}</p>;
}

function Restore({ n, onRestore }: { n: number; onRestore: () => void }) {
  return (
    <p className="flex items-center gap-2 text-[12px] leading-4 text-muted-foreground">
      <span>{fmt(copy.lab.notes.dismissed, { n })}</span>
      <button type="button" onClick={onRestore} className="tap-target underline underline-offset-2 hover:text-foreground">
        {copy.lab.notes.restore}
      </button>
    </p>
  );
}

// ---------------------------------------------------------------- the checks rail

type CheckRowProps = {
  name: string;
  state: BadgeState;
  text: string;
  check: string;
  open: boolean;
  hasDetails: boolean;
  /** An (i) next to the check's name, e.g. what the copy check shows and what it keeps back. */
  hint?: ReactNode;
  children: ReactNode;
};

/** States that ask for something: their word is ink; ok and not-checked stay muted. The state is
 *  told by the dot's shape and the word, never by a colour. */
const ACTS: ReadonlySet<BadgeState> = new Set<BadgeState>(["fix", "look"]);

/** A check's state as a dot shape and a word (WRITER's rail: a mark per category, no colour for
 *  good or bad). */
function CheckState({ state }: { state: BadgeState }) {
  return (
    <StatusDot
      tone={CHECK_TONE[state]}
      label={copy.lab.checks.states[state]}
      className={cn("shrink-0", ACTS.has(state) ? "text-foreground" : "text-muted-foreground")}
    />
  );
}

// A clean check is one line: the second line (the check's one-line sum) shows only when it says
// more than the dot's word and its details are folded (a phone), since open details say the same
// thing in full; the details show only when there is something to show (WRITER's rail). On a phone
// the details fade in when they unfold.
function CheckRow({ name, state, text, check, open, hasDetails, hint, children }: CheckRowProps) {
  const showText = !!text?.trim() && text.trim().toLowerCase() !== copy.lab.checks.states[state].toLowerCase();
  return (
    <li data-row data-check={check} data-check-state={state} className="flex min-h-9 flex-col justify-center gap-1.5 px-3 py-2 pointer-coarse:min-h-11">
      <div className="flex min-h-5 items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5">
          <LayerValue layer="ui" className="truncate text-[13px] leading-5 font-medium">
            {name}
          </LayerValue>
          {hint}
        </span>
        <CheckState state={state} />
      </div>
      {showText ? (
        <LayerValue
          as="p"
          layer="ui"
          data-check-sum
          className={cn("text-[12px] leading-4 text-muted-foreground", hasDetails && "lg:hidden", hasDetails && open && "hidden")}
        >
          {text}
        </LayerValue>
      ) : null}
      {hasDetails ? <div className={cn("animate-appear flex-col gap-1.5", open ? "flex" : "hidden lg:flex")}>{children}</div> : null}
    </li>
  );
}

function CopyHits({ hits, variants, onShow }: { hits: Hit[]; variants: Variant[]; onShow: (i: number) => void }) {
  if (!hits.length) return null;
  // What the check keeps back (the run's words and source) is in the (i) next to "Copy check".
  return (
    <ul className="flex flex-col gap-1.5">
      {hits.map((h, i) => {
        const at = beatIndex(h.where);
        const where = whereLabel(h.where, variants);
        const span = h.span ? fmt(copy.lab.checks.span, { start: h.span[0] + 1, end: h.span[1] }) : null;
        return (
          <li key={i} data-row data-copy-hit className="flex flex-col gap-0.5 rounded-md border border-dashed border-line px-2 py-1.5 text-[12px] leading-4">
            <LayerValue layer="ui" className="font-medium">
              {h.kind === "copy" ? copy.lab.checks.copyHit : fmt(copy.lab.checks.emDash, { n: h.count ?? 0 })}
            </LayerValue>
            <LayerValue layer="ui" className="text-muted-foreground">
              {where}
            </LayerValue>
            {span ? (
              <LayerValue layer="ui" className="font-mono text-mono text-muted-foreground">
                {span}
              </LayerValue>
            ) : null}
            {at !== null ? (
              <button type="button" onClick={() => onShow(at)} className="mt-0.5 w-fit underline underline-offset-2 hover:text-foreground">
                {copy.lab.checks.show}
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function Issues({ issues, variants, onShow }: { issues: Issue[]; variants: Variant[]; onShow: (i: number) => void }) {
  if (!issues.length) return null;
  return (
    <ul className="flex flex-col gap-1.5">
      {issues.map((it, i) => {
        const at = beatIndex(it.where);
        return (
          <li key={i} data-row className="flex flex-col gap-0.5 rounded-md border border-line px-2 py-1.5 text-[12px] leading-4">
            <span className="flex flex-wrap items-baseline gap-x-1.5">
              <LayerValue layer="ui" className="font-medium">
                {copy.lab.checks.levels[it.level]}
              </LayerValue>
              <LayerValue layer="ui" className="text-muted-foreground">
                {whereLabel(it.where, variants)}
              </LayerValue>
            </span>
            <LayerValue layer="ui">{stripWhere(it.message, it.where)}</LayerValue>
            {at !== null ? (
              <button type="button" onClick={() => onShow(at)} className="mt-0.5 w-fit text-muted-foreground underline underline-offset-2 hover:text-foreground">
                {copy.lab.checks.show}
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

// Read aloud, target and pace; the beat and word counts are already in the draft's header.
function LengthBlock({ lab, words, open }: { lab: LabPage; words: number; open: boolean }) {
  const badge = lab.badges.find((b) => CHECK_KEY[b.name] === "length");
  const seconds = (s: number) => fmt(copy.lab.length.seconds, { n: Math.round(s) });
  const pace = lab.est_s > 0 ? fmt(copy.lab.length.paceValue, { n: (words / lab.est_s).toFixed(1) }) : copy.lab.length.none;
  const rows: Array<[string, string]> = [
    [copy.lab.length.readAloud, seconds(lab.est_s)],
    [copy.lab.length.target, lab.target_s ? seconds(lab.target_s) : copy.lab.length.none],
    [copy.lab.length.pace, pace],
  ];
  return (
    <div data-row data-check="length" className="flex flex-col gap-2 border-t border-line px-3 py-2.5">
      <div className="flex min-h-5 items-center justify-between gap-2">
        <span data-layer="ui" className="text-[13px] leading-5 font-medium">
          {copy.lab.length.title}
        </span>
        {/* On a phone the numbers are folded, so the row says the read-aloud length at a glance. */}
        <LayerValue layer="facts" className="ml-auto min-w-0 truncate text-muted-foreground tabular-nums lg:hidden">
          {lab.target_s
            ? fmt(copy.lab.length.glance, { est: Math.round(lab.est_s), target: Math.round(lab.target_s) })
            : fmt(copy.lab.length.glanceNoTarget, { est: Math.round(lab.est_s) })}
        </LayerValue>
        {badge ? <CheckState state={badge.state} /> : null}
      </div>
      <LengthBar beats={lab.beats} est_s={lab.est_s} target_s={lab.target_s} />
      <dl className={cn("flex-col gap-1", open ? "flex" : "hidden lg:flex")}>
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-2">
            <dt className="text-[12px] leading-4 text-muted-foreground">{k}</dt>
            <dd>
              <LayerValue layer="facts" className="tabular-nums">
                {v}
              </LayerValue>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
