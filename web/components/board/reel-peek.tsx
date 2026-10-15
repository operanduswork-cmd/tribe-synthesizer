"use client";

// The peek panel (Twenty reference): a 420px panel over the right of the table on a laptop, a
// bottom sheet on a phone. Header: close, the handle, the shortcode, previous / next. Body:
// counts (the counts line, as-of date, own-reels strip, flags, discount), the creator's own
// baseline, facts and shape labels with Accept (analysis only, D31: no recreate command). Footer: Instagram and
// "Open ⌘↵" to the reel page.
//
// The peek never shows a brain value: no TRIBE field, line or moment appears here (D20, D21).
// It slides in (from the right on a laptop, from below on a phone) with a short fade; under
// reduced motion it simply appears. The own-reels strip marks this reel in counts teal; its
// legend sits behind an (i) (D30, less text), and the peek carries no other notes.
// Keys: Esc closes, ⌘/Ctrl+Enter opens the reel page, ↑/↓ move to the previous / next reel.

import { ArrowUpRightIcon, ChevronDownIcon, ChevronUpIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { FlagList } from "@/components/board/flag-list";
import { hasSuggested, reelHref, shapeCell, shapeHint, type Reel } from "@/components/board/model";
import { PeerStrip } from "@/components/board/peer-strip";
import { JobButton } from "@/components/shared/job-button";
import { LayerTag } from "@/components/shared/layer-tag";
import { LayerValue } from "@/components/shared/layer-value";
import { ShapeChip } from "@/components/shared/shape-chip";
import { Button } from "@/components/ui/button";
import { copy } from "@/lib/copy";
import { cn } from "@/lib/utils";

const c = copy.board;

/** A peek section. Its heading is the layer tag alone when the title would only repeat it
 *  ("Counts COUNT"); a title is given where it says more ("Own baseline COUNT"). */
function Section({ title, layer, children }: { title?: string; layer?: "counts" | "facts" | "shape"; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5 border-b border-line px-4 py-4 last:border-b-0">
      <h3 data-layer="ui" className="flex items-center gap-2 text-mono font-medium text-muted-foreground">
        {title ? <span>{title}</span> : null}
        {layer ? <LayerTag layer={layer} /> : null}
      </h3>
      {children}
    </section>
  );
}

/** One label / value row (Twenty's field rows): grey label on the left, value on the right. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div data-line="field" className="grid min-h-7 grid-cols-[88px_1fr] items-start gap-3 text-ui">
      <span data-layer="ui" className="pt-0.5 text-muted-foreground">
        {label}
      </span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function ShapeField({ label, text }: { label: string; text: string }) {
  const s = shapeCell(text);
  return (
    <Field label={label}>
      {s ? (
        <ShapeChip label={s.label} status={s.status} hint={shapeHint(s.status)} />
      ) : (
        <LayerValue layer="shape" className="text-muted-foreground">
          {c.notTagged}
        </LayerValue>
      )}
    </Field>
  );
}

type PeekProps = {
  reel: Reel | null;
  baseline: string[];
  onClose: () => void;
  onMove: (step: -1 | 1) => void;
  canPrev: boolean;
  canNext: boolean;
};

function typing(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

export function ReelPeek({ reel, baseline, onClose, onMove, canPrev, canNext }: PeekProps) {
  const router = useRouter();
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const open = reel !== null;
  const sc = reel?.sc ?? null;

  // Focus the close button when the panel opens; give focus back when it closes.
  useEffect(() => {
    if (!open) return;
    returnTo.current = document.activeElement as HTMLElement | null;
    closeRef.current?.focus({ preventScroll: true });
    return () => {
      const back = returnTo.current;
      if (back && document.contains(back)) back.focus({ preventScroll: true });
    };
  }, [open]);

  useEffect(() => {
    if (!sc) return;
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || document.querySelector("[role=menu], [role=dialog][aria-modal=true]")) return;
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        router.push(reelHref(sc!));
      } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !typing(e.target)) {
        e.preventDefault();
        onMove(e.key === "ArrowDown" ? 1 : -1);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sc, onClose, onMove, router]);

  if (!reel) return null;

  return (
    <>
      {/* Phone only: a scrim behind the bottom sheet. */}
      <button type="button" aria-label={c.peek.close} tabIndex={-1} onClick={onClose} className="fixed inset-0 z-50 animate-in bg-black/30 duration-(--motion-base) fade-in-0 md:hidden" />
      <aside
        role="dialog"
        aria-modal={false}
        aria-labelledby="board-peek-title"
        data-board="peek"
        className={cn(
          "fixed z-50 flex flex-col border-line bg-surface shadow-lg",
          "animate-in duration-(--motion-base) ease-(--motion-ease-out) fade-in-0 slide-in-from-bottom-6 md:slide-in-from-bottom-0 md:slide-in-from-right-6",
          "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-xl border-t pb-[env(safe-area-inset-bottom)]",
          "md:inset-x-auto md:top-topbar md:right-0 md:bottom-0 md:max-h-none md:w-[420px] md:rounded-none md:border-t-0 md:border-l md:pb-0",
        )}
      >
        <header data-layer="ui" className="flex h-12 shrink-0 items-center gap-2 border-b border-line pr-2 pl-2">
          <Button ref={closeRef} variant="ghost" size="icon-sm" onClick={onClose} aria-label={c.peek.close} title={c.peek.closeKey} className="pointer-coarse:size-11">
            <XIcon aria-hidden />
          </Button>
          <div className="flex min-w-0 flex-1 items-baseline gap-2">
            <h2 id="board-peek-title" className="truncate text-sm font-semibold">
              {reel.handle}
            </h2>
            <span className="shrink-0 font-mono text-mono text-muted-foreground">{reel.sc}</span>
          </div>
          <Button variant="ghost" size="icon-sm" onClick={() => onMove(-1)} disabled={!canPrev} aria-label={c.peek.prev} className="pointer-coarse:size-11">
            <ChevronUpIcon aria-hidden />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => onMove(1)} disabled={!canNext} aria-label={c.peek.next} className="pointer-coarse:size-11">
            <ChevronDownIcon aria-hidden />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <Section layer="counts">
            <LayerValue layer="counts" as="p" data-line="counts" className="text-sm font-medium">
              {reel.counts}
            </LayerValue>
            <LayerValue layer="counts" as="p" data-line="as-of" className="-mt-1.5 text-mono text-muted-foreground">
              {reel.as_of}
            </LayerValue>
            {reel.peer ? <PeerStrip peer={reel.peer} /> : null}
            <Field label={c.peek.flags}>
              <FlagList reel={reel} />
            </Field>
            {reel.discount ? (
              <Field label={c.peek.discount}>
                <LayerValue layer="counts" className="text-muted-foreground">
                  {reel.discount}
                </LayerValue>
              </Field>
            ) : null}
          </Section>

          {baseline.length ? (
            <Section title={c.peek.baseline} layer="counts">
              <ul className="flex flex-col gap-1">
                {baseline.map((item, i) => (
                  <LayerValue key={i} layer="counts" as="li" className="text-ui text-muted-foreground">
                    {item}
                  </LayerValue>
                ))}
              </ul>
            </Section>
          ) : null}

          <Section layer="facts">
            <LayerValue layer="facts" as="p" data-line="facts">
              {reel.meta}
            </LayerValue>
          </Section>

          <Section layer="shape">
            <ShapeField label={c.peek.hook} text={reel.cells.hook} />
            <ShapeField label={c.peek.format} text={reel.cells.format} />
            <ShapeField label={c.peek.cta} text={reel.cells.cta} />
            {hasSuggested(reel) ? (
              <div className="flex flex-col gap-1.5 pt-1">
                <JobButton kind="reel.accept" args={{ sc: reel.sc, field: "all" }} label={c.peek.acceptAll} />
              </div>
            ) : null}
          </Section>
        </div>

        <footer data-layer="ui" className="flex h-12 shrink-0 items-center gap-2 border-t border-line px-3">
          <a
            href={reel.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-ui text-muted-foreground hover:bg-subtle hover:text-foreground pointer-coarse:h-11"
          >
            {c.peek.instagram}
            <ArrowUpRightIcon className="size-3.5" aria-hidden />
          </a>
          <Button asChild size="sm" className="ml-auto h-8 gap-2 pointer-coarse:h-11">
            <Link href={reelHref(reel.sc)} data-board="peek-open">
              <span>{c.peek.open}</span>
              <kbd className="hidden font-mono text-[10px] opacity-70 md:inline">{c.peek.openKey}</kbd>
            </Link>
          </Button>
        </footer>
      </aside>
    </>
  );
}
