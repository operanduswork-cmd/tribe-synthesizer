// The Beats tab: the shape labels (hook shape, format, call to action) and the beats, each
// outlined while Claude only suggested it and filled once accepted, with Accept / Reject.
//
// Hook shape, format and call to action come from this reel's board row (the reel page does not
// carry them). Beats are accepted or rejected as a group: the hosted page leaves out rejected
// beats, so a beat's place in this list is not its index in reel.json, and "beats.<n>" from here
// could hit the wrong beat. One beat at a time works on the laptop. Round 3 (D30): every
// explanation, the rebuild note included, sits behind an (i).

import type { ReactNode } from "react";

import { InfoHint } from "@/components/shared/info-hint";
import { JobButton } from "@/components/shared/job-button";
import { LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { ShapeChip, type ShapeStatus } from "@/components/shared/shape-chip";
import { copy } from "@/lib/copy";
import type { BoardPage, ReelPage } from "@/lib/hosted";
import { jobKindLabel } from "@/lib/job-kinds";
import { cn } from "@/lib/utils";

import { LabelActions } from "./label-actions";
import { CARD_CLASS, ROW_HOVER_CLASS } from "./reel-card";
import { SeekChip } from "./reel-time";

const L = copy.reel.labels;
const SUGGESTED = " (suggested)";

type BoardRow = BoardPage["reels"][number];
type Field = keyof typeof L.fields;
type Label = { field: Field; label: string; status: ShapeStatus | null } | { field: Field; label: null; status: null };

/** A board cell ("cold open question" or "list tease (suggested)") as a label and its status.
 *  The CTA cell may be a facts guess when no label exists, so only a suggested CTA gets a status. */
function fieldLabel(field: Field, row: BoardRow): Label {
  const cell = field === "hook_shape" ? row.cells.hook : field === "format" ? row.cells.format : row.cells.cta;
  const clean = field === "hook_shape" ? row.filter.hook : field === "format" ? row.filter.format : null;
  const suggested = cell.endsWith(SUGGESTED);
  const label = suggested ? cell.slice(0, -SUGGESTED.length) : cell;
  if (field !== "cta" && !clean) return { field, label: null, status: null };
  if (field === "cta" && !suggested) return { field, label, status: null };
  return { field, label, status: suggested ? "suggested" : "accepted" };
}

/** The section header: SHAPE tag, title, and the section's explanation behind an (i) (Xero /
 *  Plain reference: the hint sits right after the title, never inside it). */
function Header({ title, hint, children }: { title: string; hint?: { label: string; text: string }; children?: ReactNode }) {
  return (
    <header data-layer="ui" className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2">
      <div className="flex items-center gap-2">
        <LayerTag layer="shape" />
        <h2 className="text-ui font-medium">{title}</h2>
        {hint ? (
          <InfoHint label={hint.label} align="start">
            {hint.text}
          </InfoHint>
        ) : null}
      </div>
      {children ? <div className="flex flex-wrap items-center gap-2">{children}</div> : null}
    </header>
  );
}

export function BeatsPanel({ reel, row }: { reel: ReelPage; row: BoardRow | null }) {
  const labels = row ? (["hook_shape", "format", "cta"] as const).map((f) => fieldLabel(f, row)) : [];
  const anyLabelSuggested = labels.some((l) => l.status === "suggested");
  const anyBeatSuggested = reel.beats.some((b) => b.suggested);
  const sc = reel.shortcode;

  return (
    <>
      <section className={CARD_CLASS}>
        <Header title={L.title} hint={{ label: L.hintLabel, text: L.hint }}>
          {anyLabelSuggested || anyBeatSuggested ? <LabelActions sc={sc} field="all" acceptLabel={L.acceptAll} /> : null}
          <JobButton kind="coach.tag_shapes" args={{ sc }} label={jobKindLabel("coach.tag_shapes")} size="xs" />
        </Header>
        {row ? (
          <ul className="flex flex-col py-2">
            {labels.map((l) => (
              <li
                key={l.field}
                data-row
                className={cn(ROW_HOVER_CLASS, "flex min-h-9 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-1 pointer-coarse:min-h-11")}
              >
                <span className="flex min-w-0 items-center gap-3">
                  <span data-layer="ui" className="w-28 shrink-0 text-ui text-muted-foreground">
                    {L.fields[l.field]}
                  </span>
                  {l.label === null ? (
                    <span data-layer="ui" className="text-ui text-muted-foreground">
                      {L.notTagged}
                    </span>
                  ) : l.status ? (
                    <ShapeChip label={l.label} status={l.status} />
                  ) : (
                    <LayerValue layer="shape" className="truncate text-ui">
                      {l.label}
                    </LayerValue>
                  )}
                </span>
                {l.status === "suggested" ? (
                  <LabelActions sc={sc} field={l.field} acceptLabel={L.accept} rejectLabel={L.reject} />
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p data-layer="ui" className="px-4 py-3 text-ui text-muted-foreground">
            {L.noBoard}
          </p>
        )}
      </section>

      <section className={CARD_CLASS}>
        <Header
          title={copy.reel.beats.title}
          hint={anyBeatSuggested ? { label: copy.reel.beats.groupHintLabel, text: copy.reel.beats.groupHint } : undefined}
        >
          {anyBeatSuggested ? (
            <LabelActions sc={sc} field="beats" acceptLabel={copy.reel.beats.acceptAll} rejectLabel={copy.reel.beats.rejectAll} />
          ) : null}
        </Header>
        {reel.beats.length ? (
          <ol className="flex flex-col py-2">
            {reel.beats.map((b, i) => (
              <li key={i} data-row className={cn(ROW_HOVER_CLASS, "flex min-h-9 items-center gap-3 px-4 py-1 pointer-coarse:min-h-11")}>
                <SeekChip time={b.chip} layer="shape" className="min-w-[5.5rem] justify-center" />
                <ShapeChip label={b.name} field={b.kind} status={b.suggested ? "suggested" : "accepted"} className="min-w-0" />
              </li>
            ))}
          </ol>
        ) : (
          <p data-layer="ui" className="px-4 py-3 text-ui text-muted-foreground">
            {reel.beats_empty}
          </p>
        )}
      </section>

      <div data-layer="ui" className="flex flex-wrap items-center gap-2 px-1">
        <JobButton kind="patterns.build" label={jobKindLabel("patterns.build")} size="xs" />
        <InfoHint label={L.rebuildLabel} align="start">
          {L.rebuild}
        </InfoHint>
      </div>
    </>
  );
}
