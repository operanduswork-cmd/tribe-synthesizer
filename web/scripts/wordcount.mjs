// Visible word count per page, for the round 3 text cut (plan B1): the "before" and "after"
// figures. Opens each page at laptop (1280x800) and phone (390x844, touch) widths in the
// installed Chrome, waits for the network to settle, scrolls once through the page so lazy parts
// render, then counts the words of document.body.innerText: the text a reader sees, with nothing
// opened (no popovers, no (i) hints, no folds). A word is a run of non-space characters holding
// at least one letter or digit, so separators like a middle dot are not words.
// Extra columns: words inside <main>, the rest (header, nav, footer), and words in sr-only
// elements (inside innerText, but not seen on screen).
// Writes ../reports/round3-words-<label>.json, outside web/ (scripts/ is not on the
// .vercelignore allowlist, so nothing here is uploaded).
// Usage: node scripts/wordcount.mjs <label> [baseUrl]   (either order works)
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const base = (args.find((a) => /^https?:\/\//.test(a)) || "http://127.0.0.1:3123").replace(/\/+$/, "");
const label = args.find((a) => !/^https?:\/\//.test(a)) || "before";
if (!/^[A-Za-z0-9_-]{1,40}$/.test(label)) {
  console.error("label: letters, digits, - or _ only");
  process.exit(2);
}
const outDir = path.resolve(import.meta.dirname, "..", "..", "reports");
const outFile = path.join(outDir, `round3-words-${label}.json`);

const PAGES = [
  "/board",
  "/reels/DEMO0000001",
  "/reels/DcwCCgivcIQ",
  "/reels/Dd2FOEVxaap",
  "/patterns",
  "/lab",
  "/lab/20261008-example-tribe-explainer",
  "/settings/jobs",
];
const WIDTHS = [
  { name: "laptop", viewport: { width: 1280, height: 800 }, isMobile: false, hasTouch: false },
  { name: "phone", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
];

// Runs in the page. Counts words the same way for every part.
function countInPage() {
  const count = (t) => (t || "").split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
  const body = document.body;
  const main = document.querySelector("main");
  const all = count(body.innerText);
  const inMain = main ? count(main.innerText) : 0;
  // Visually hidden text (Tailwind sr-only or the same clip trick): count the outermost only.
  const hidden = [...body.querySelectorAll("*")].filter((el) => {
    const s = getComputedStyle(el);
    if (s.display === "none") return false;
    const r = el.getBoundingClientRect();
    return el.classList.contains("sr-only") ||
      (s.position === "absolute" && r.width <= 1 && r.height <= 1 && (s.overflow === "hidden" || s.clip !== "auto"));
  });
  const outer = hidden.filter((el) => !hidden.some((o) => o !== el && o.contains(el)));
  const srOnly = outer.reduce((n, el) => n + count(el.innerText), 0);
  return { words: all, main: inMain, shell: all - inMain, srOnly };
}

async function scrollThrough(page) {
  await page.evaluate(async () => {
    const step = Math.max(200, Math.floor(window.innerHeight * 0.8));
    for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 120));
    }
    window.scrollTo(0, 0);
  });
}

// SwiftShader WebGL, as playwright.config.ts, so the 3D brain draws instead of its fallback.
const browser = await chromium.launch({ channel: "chrome", args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const rows = [];
try {
  for (const w of WIDTHS) {
    const ctx = await browser.newContext({ viewport: w.viewport, isMobile: w.isMobile, hasTouch: w.hasTouch, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    for (const p of PAGES) {
      const errors = [];
      const onConsole = (m) => m.type() === "error" && errors.push(m.text().slice(0, 160));
      page.on("console", onConsole);
      const res = await page.goto(base + p, { waitUntil: "networkidle", timeout: 60_000 });
      await page.waitForTimeout(400);
      await scrollThrough(page);
      await page.waitForLoadState("networkidle").catch(() => {});
      await page.waitForTimeout(400);
      const c = await page.evaluate(countInPage);
      page.off("console", onConsole);
      rows.push({ page: p, width: w.name, status: res ? res.status() : 0, ...c, consoleErrors: errors.length });
    }
    await ctx.close();
  }
} finally {
  await browser.close();
}

const sum = (list, k) => list.reduce((n, r) => n + r[k], 0);
const totals = {};
for (const w of WIDTHS) {
  const list = rows.filter((r) => r.width === w.name);
  totals[w.name] = { words: sum(list, "words"), main: sum(list, "main"), shell: sum(list, "shell"), srOnly: sum(list, "srOnly") };
}
totals.all = { words: sum(rows, "words"), main: sum(rows, "main"), shell: sum(rows, "shell"), srOnly: sum(rows, "srOnly") };

const pad = (v, n) => String(v).padStart(n);
const padEnd = (v, n) => String(v).padEnd(n);
console.log(`Visible words, label ${label}, ${base}`);
console.log(`${padEnd("page", 40)} ${padEnd("width", 7)} ${pad("status", 6)} ${pad("words", 6)} ${pad("main", 6)} ${pad("shell", 6)} ${pad("srOnly", 6)}`);
for (const r of rows) {
  console.log(`${padEnd(r.page, 40)} ${padEnd(r.width, 7)} ${pad(r.status, 6)} ${pad(r.words, 6)} ${pad(r.main, 6)} ${pad(r.shell, 6)} ${pad(r.srOnly, 6)}`);
}
for (const [k, t] of Object.entries(totals)) {
  console.log(`${padEnd(`TOTAL ${k}`, 40)} ${padEnd("", 7)} ${pad("", 6)} ${pad(t.words, 6)} ${pad(t.main, 6)} ${pad(t.shell, 6)} ${pad(t.srOnly, 6)}`);
}
const errs = rows.filter((r) => r.consoleErrors || r.status !== 200);
if (errs.length) console.log(`check: ${errs.map((r) => `${r.page} ${r.width} status ${r.status} console errors ${r.consoleErrors}`).join("; ")}`);

mkdirSync(outDir, { recursive: true });
writeFileSync(outFile, JSON.stringify({ label, base, measuredAt: new Date().toISOString(), method: "document.body.innerText, words with a letter or digit, nothing opened, one scroll pass", rows, totals }, null, 2) + "\n");
console.log(`wrote ${outFile}`);
