"use client";

// The Import demo (16 Oct): paste reel links, press Run demo, see what real results will look like.
// Everything is made up from the link (a seeded hash), nothing is fetched, no job is queued and no
// money is spent. Each reel's results sit in four separate boxes (D20): facts, counts, shape and
// the predicted average-brain response, each on its own scale, never compared across reels (D21).

import { DownloadIcon, PlayIcon } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { InfoHint } from "@/components/shared/info-hint";
import { LayerDot, LayerTag } from "@/components/shared/layer-tag";
import { buttonVariants } from "@/components/ui/button";
import { copy, fmt } from "@/lib/copy";
import { cn } from "@/lib/utils";

const MAX_LINKS = 6;
const REEL_RE = /instagram\.com\/(?:[\w.]+\/)?(?:reels?|p|tv)\/([A-Za-z0-9_-]{5,20})/i;

function hash(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** A small seeded random stream (mulberry32): same link, same demo. */
function rng(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Demo = {
  code: string;
  facts: { duration_s: number; first_word_s: number; speech: boolean };
  counts: { plays: number; likes: number; comments: number };
  shape: { hook: string; format: string; cta: string };
  brain: { framing: string; networks: { name: string; values: number[] }[]; peak_s: number };
};

function build(code: string): Demo {
  const r = rng(hash(code));
  const duration = 14 + Math.floor(r() * 44);
  const nets = copy.import.networks.map((name) => {
    const phase = r() * 6;
    const amp = 0.6 + r() * 1.2;
    const values = Array.from({ length: duration }, (_, s) =>
      Math.max(-2.5, Math.min(2.5, Math.sin(s / 3.2 + phase) * amp + (r() - 0.5) * 0.8)),
    );
    return { name, values: values.map((v) => Math.round(v * 100) / 100) };
  });
  let peak = 0;
  let best = -Infinity;
  for (let s = 0; s < duration; s++) {
    const m = nets.reduce((a, n) => a + n.values[s], 0) / nets.length;
    if (m > best) {
      best = m;
      peak = s;
    }
  }
  const pick = (a: string[]) => a[Math.floor(r() * a.length)];
  return {
    code,
    facts: { duration_s: duration, first_word_s: Math.round(r() * 20) / 10, speech: true },
    counts: { plays: 8000 + Math.floor(r() * 900000), likes: 300 + Math.floor(r() * 40000), comments: 5 + Math.floor(r() * 900) },
    shape: { hook: pick(copy.import.hooks), format: pick(copy.import.formats), cta: pick(copy.import.ctas) },
    brain: { framing: copy.export.framing, networks: nets, peak_s: peak },
  };
}

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** One network over time on the reel's one scale, with a dashed zero line. */
function Spark({ values }: { values: number[] }) {
  const w = 160;
  const h = 28;
  const n = values.length;
  const x = (i: number) => (i / Math.max(1, n - 1)) * w;
  const y = (v: number) => h / 2 - (v / 2.5) * (h / 2);
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg aria-hidden viewBox={`0 0 ${w} ${h}`} className="h-7 w-40 max-w-full shrink-0">
      <line x1="0" x2={w} y1={h / 2} y2={h / 2} className="stroke-line" strokeWidth="1" strokeDasharray="2 2" />
      <polyline points={pts} fill="none" strokeWidth="1.4" className="stroke-brain-warm" />
    </svg>
  );
}

function Box({ layer, title, children }: { layer: "facts" | "counts" | "shape" | "brain"; title: string; children: ReactNode }) {
  return (
    <section data-import-box={layer} className="sleek-card min-w-0 rounded-lg p-3">
      <h3 className="mb-2 flex items-center gap-1.5 text-sm font-medium">
        <LayerDot layer={layer} />
        {title}
        <LayerTag layer={layer} className="ml-auto" />
      </h3>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-line py-1 text-ui first:border-t-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right tabular-nums">{value}</span>
    </div>
  );
}

export function ImportDemo() {
  const [text, setText] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [empty, setEmpty] = useState(false);
  const [capped, setCapped] = useState(false);
  const demos = useMemo(() => (codes ?? []).map(build), [codes]);

  function run() {
    const found: string[] = [];
    for (const line of text.split(/\s+/)) {
      const m = REEL_RE.exec(line);
      if (m && !found.includes(m[1])) found.push(m[1]);
    }
    setEmpty(found.length === 0);
    setCapped(found.length > MAX_LINKS);
    setCodes(found.slice(0, MAX_LINKS));
  }

  function download() {
    const body = { meta: { framing: copy.export.framing, note: copy.import.banner }, reels: demos };
    const url = URL.createObjectURL(new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "tribe-import-demo.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  const btn = cn(buttonVariants({ variant: "outline", size: "lg" }), "min-h-11 px-4");
  return (
    <div data-import-demo="" className="flex min-w-0 flex-col gap-4">
      <div className="flex items-start gap-1.5">
        <div className="min-w-0 flex-1">
          <p data-import-banner="" className="mb-2 text-xs text-muted-foreground">
            {copy.import.banner}
          </p>
          <textarea
            data-import-input=""
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={copy.import.placeholder}
            aria-label={copy.import.title}
            rows={4}
            className="sleek-card block w-full min-w-0 resize-y rounded-lg p-3 font-mono text-xs leading-5"
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" data-import-run="" onClick={run} className={cn(buttonVariants({ variant: "default", size: "lg" }), "min-h-11 px-4")}>
              <PlayIcon aria-hidden className="size-4" />
              {copy.import.run}
            </button>
            <button
              type="button"
              onClick={() => {
                setText("");
                setCodes(null);
                setEmpty(false);
                setCapped(false);
              }}
              className={btn}
            >
              {copy.import.clear}
            </button>
            {demos.length ? (
              <button type="button" data-import-download="" onClick={download} className={cn(btn, "ml-auto")}>
                <DownloadIcon aria-hidden className="size-4" />
                {copy.import.download}
              </button>
            ) : null}
          </div>
        </div>
        <InfoHint label={copy.import.hintLabel}>{copy.import.hint}</InfoHint>
      </div>

      {empty ? <p className="text-sm text-muted-foreground">{copy.import.noLinks}</p> : null}
      {capped ? <p className="text-xs text-muted-foreground">{fmt(copy.import.cap, { n: MAX_LINKS })}</p> : null}

      {demos.map((d) => (
        <article key={d.code} data-import-reel={d.code} className="flex min-w-0 flex-col gap-3">
          <h2 className="font-mono text-sm">
            {fmt(copy.import.reel, { code: d.code })} <span className="text-muted-foreground">{copy.import.demoTag}</span>
          </h2>
          <div className="grid min-w-0 gap-3 md:grid-cols-3">
            <Box layer="facts" title={copy.import.factsTitle}>
              <Row label={copy.import.duration} value={clock(d.facts.duration_s)} />
              <Row label={copy.import.firstWord} value={clock(d.facts.first_word_s)} />
              <Row label={copy.import.speech} value={copy.import.speechYes} />
            </Box>
            <Box layer="counts" title={copy.import.countsTitle}>
              <Row label={copy.import.plays} value={d.counts.plays.toLocaleString("en-US")} />
              <Row label={copy.import.likes} value={d.counts.likes.toLocaleString("en-US")} />
              <Row label={copy.import.comments} value={d.counts.comments.toLocaleString("en-US")} />
            </Box>
            <Box layer="shape" title={copy.import.shapeTitle}>
              <Row label={copy.import.hook} value={d.shape.hook} />
              <Row label={copy.import.format} value={d.shape.format} />
              <Row label={copy.import.cta} value={d.shape.cta} />
            </Box>
          </div>
          <Box layer="brain" title={copy.import.brainTitle}>
            <p className="mb-2 text-xs text-muted-foreground">
              {fmt(copy.import.peak, { time: clock(d.brain.peak_s) })}
            </p>
            <ul className="grid min-w-0 gap-x-6 gap-y-1 md:grid-cols-2">
              {d.brain.networks.map((n, i) => (
                <li key={n.name} className="flex items-center justify-between gap-3 border-t border-line py-1 text-ui">
                  <span className="min-w-0 truncate">
                    <span className="tabular-nums text-muted-foreground">{i + 1}</span> {n.name}
                  </span>
                  <Spark values={n.values} />
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">{copy.import.brainNote}</p>
          </Box>
        </article>
      ))}
    </div>
  );
}
