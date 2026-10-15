// Patterns screen in fixtures mode, at phone (390x844) and laptop (1280x800) widths: no console
// errors, no sideways scroll, the licence footer, the D20 wall (no counts value shares a row or
// line with a brain value, and nothing from a deep read on this page at all), no banned words in
// the visible text (the lists are read from dashboard/render.py, the one source of the rules),
// and the screen's own rules: every pattern row shows two bars or "outliers only, no comparison
// yet", rows keep the order the laptop built (never sorted by a count), no ratio in a row, the
// row opens its source reels and Rebuild is live (fixtures mode). Round 4 (D31, analysis only):
// no Recreate, no draft links and no drafts line anywhere on the page; names are cut to a few
// words (the full name is the hover text), each bar shows one count (its "k of n" is the bar's
// name and hover text), and "outliers only" is two words in the row (the full line on hover).
// Round 2: outlier bars and dots are the counts teal and normal ones a hue-free grey (never a
// red/green verdict), bars grow in while counts never move and reduced motion stops it all, and
// the label toggle's thumb slides to the pick.
// Round 3 (text cut): no subtitle, stamp, legend card or fold body. The footer is one short line
// whose (i) opens to the full licence text. Every explanation sits behind an (i) (44px on touch,
// never inside a heading): the lead's meaning behind its own, and the group definitions, the
// caveat notes and the population behind the one in the list's key row, each word for word.
// Screenshots, light and dark, go to test-results/shots/patterns-<project>-<scheme>.png.

import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import en from "../copy/en.json";
import fixture from "../fixtures/patterns.json";

// ---------------------------------------------------------------- rules from dashboard/render.py

const RULES = readFileSync(path.resolve(__dirname, "../../dashboard/render.py"), "utf8");

/** The strings of a module-level tuple, e.g. RATING_PATTERNS = (r"...", ...). */
function pyStrings(name: string): string[] {
  const at = RULES.search(new RegExp(`^${name}\\s*=\\s*\\(`, "m"));
  if (at < 0) throw new Error(`dashboard/render.py has no ${name}`);
  const token = /\s+|,|#[^\n]*|r?"((?:\\.|[^"\\])*)"|\)/y;
  const out: string[] = [];
  token.lastIndex = RULES.indexOf("(", at) + 1;
  for (;;) {
    const m = token.exec(RULES);
    if (!m) throw new Error(`dashboard/render.py: cannot read ${name}`);
    if (m[0] === ")") return out;
    if (m[1] !== undefined) out.push(m[1]);
  }
}

function pyRegex(name: string): string {
  const m = RULES.match(new RegExp(`^${name}\\s*=\\s*re\\.compile\\(r"((?:\\\\.|[^"\\\\])*)"`, "m"));
  if (!m) throw new Error(`dashboard/render.py has no ${name}`);
  return m[1];
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const termPattern = (t: string) => t.split(/[\s-]+/).map(escape).join("[\\s-]*");

// Every *_WORDS tuple is a banned list (the three in render.py today); the ones named *_CS are
// banned only in capitals. All others are matched without case, plurals included. Names are read
// from the file, not written here, so this file's strings pass test_web_copy's literal scan.
const WORD_LISTS = [...RULES.matchAll(/^(\w*_WORDS\w*)\s*=\s*\(/gm)].map((m) => m[1]);
const WORDS_CS = WORD_LISTS.filter((n) => n.endsWith("_CS")).flatMap(pyStrings);
const WORDS_CI = WORD_LISTS.filter((n) => !n.endsWith("_CS")).flatMap(pyStrings);
const RATINGS = pyStrings("RATING_PATTERNS");
const BANNED: RegExp[] = [
  new RegExp(`(?<![A-Za-z0-9])(?:${WORDS_CI.map(termPattern).join("|")})(?:e?s)?(?![A-Za-z0-9])`, "gi"),
  new RegExp(`(?<![A-Za-z0-9])(?:${WORDS_CS.join("|")})(?![A-Za-z0-9])`, "g"),
  new RegExp(pyRegex("_BANNED_PREFIX_RE"), "gi"),
  new RegExp(RATINGS.join("|"), "gi"),
];

function bannedIn(text: string): string[] {
  return BANNED.flatMap((rx) => [...text.matchAll(rx)].map((m) => m[0]));
}

// ---------------------------------------------------------------- helpers

type FixturePattern = (typeof fixture.patterns)[number];
const KIND_ORDER = ["hook", "structure", "cta", "format"];
/** The row order the page must keep: catalog order, then the laptop's order, folded rows last. */
const EXPECTED_ORDER = KIND_ORDER.flatMap((k) => {
  const rows = fixture.patterns.filter((p: FixturePattern) => p.kind === k);
  return [...rows.filter((p) => !p.zero), ...rows.filter((p) => p.zero)].map((p) => p.id);
});

async function load(page: Page, scheme: "light" | "dark" = "light"): Promise<string[]> {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  await page.emulateMedia({ colorScheme: scheme });
  await page.goto("/patterns");
  await page.waitForLoadState("networkidle");
  await expect(page.locator("[data-pattern-list]")).toBeVisible();
  return errors;
}

/** Opens an (i) hint by touch on a phone (checking its 44px hit area) or by click on a laptop,
 *  and returns the open hint. */
async function openHint(page: Page, trigger: Locator, phone: boolean): Promise<Locator> {
  await expect(trigger).toHaveCount(1);
  if (phone) {
    // A 16px icon with a 44px hit area on touch.
    const hit = await trigger.evaluate((el) => {
      const s = getComputedStyle(el, "::before");
      return Math.min(parseFloat(s.width), parseFloat(s.height));
    });
    expect(hit).toBeGreaterThanOrEqual(44);
    await trigger.tap();
  } else {
    await trigger.click();
  }
  const hint = page.locator("[data-hint]");
  await expect(hint).toBeVisible();
  return hint;
}

async function closeHint(page: Page) {
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-hint]")).toHaveCount(0);
}

const footerText = (template: string) =>
  template.replace("{tribe}", en.footer.tribe).replace("{licence}", en.footer.licence).replace("{llama}", en.footer.llama);

/** The texts the groups (i) holds, each word for word: what the legend card and its fold showed. */
const GROUP_HINT_TEXTS = [
  en.patterns.legend.outliersDef,
  en.patterns.legend.normalDef,
  ...fixture.notes,
  ...fixture.population,
  en.patterns.about,
  en.patterns.zero.body,
];

/** Rows (li, tr, p, [data-row]) that hold both a counts value and a brain value. */
async function wallBreaks(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const ROW = "[data-row], li, tr, p, [role=row]";
    const out: string[] = [];
    const pairs: Array<[string, string]> = [
      ['[data-layer="brain"]', '[data-layer="counts"]'],
      ['[data-layer="counts"]', '[data-layer="brain"]'],
    ];
    for (const [self, other] of pairs) {
      for (const el of document.querySelectorAll(self)) {
        const row = el.closest(ROW);
        if (row?.querySelector(other)) out.push((row.textContent ?? "").slice(0, 80));
      }
    }
    return out;
  });
}

// ---------------------------------------------------------------- tests

test("patterns: the word rules were read from dashboard/render.py", () => {
  expect(WORD_LISTS.length).toBeGreaterThanOrEqual(3);
  expect(WORDS_CI.length).toBeGreaterThan(20);
  expect(WORDS_CS.length).toBeGreaterThan(0);
  expect(RATINGS.length).toBeGreaterThan(0);
  // A planted word from each list is caught; a pattern contrast is not a rating.
  for (const w of [WORDS_CI[0], WORDS_CI[WORDS_CI.length - 1], WORDS_CS[0]]) expect(bannedIn(`a ${w} b`)).not.toEqual([]);
  expect(bannedIn("outliers 3/10 vs normal 5/31")).toEqual([]);
});

test("patterns: page rules, wall, words and layout", async ({ page }, info) => {
  const errors = await load(page);
  const phone = info.project.name === "phone";

  // The footer: one short line in view; its (i) opens to exactly the full LICENCE 12 A text,
  // the framing included.
  const footer = page.locator("footer[data-licence]");
  await expect(footer).toContainText(en.footer.llama);
  await expect(footer).toContainText("CC BY-NC 4.0");
  const licence = await openHint(page, footer.getByRole("button", { name: en.footer.hint, exact: true }), phone);
  await expect(licence.locator("[data-licence-text]")).toHaveText(footerText(en.footer.text));
  await expect(licence).toContainText("predicted average-brain response");
  await closeHint(page);

  // Round 3 text cut: no subtitle, no stamp, no family or level in a closed row.
  await expect(page.locator("main header p")).toHaveCount(0);
  await expect(page.getByText(fixture.stamp, { exact: true })).toHaveCount(0);
  await expect(page.locator("[data-row-summary] [data-pattern-family]")).toHaveCount(0);

  // No sideways scroll at this width.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  // The wall (D20), and nothing from a deep read in this page's content at all (the shell's
  // freshness line names the last TRIBE run on every page).
  expect(await wallBreaks(page)).toEqual([]);
  await expect(page.locator('main [data-layer="brain"]')).toHaveCount(0);

  // Every value carries a layer: the pattern labels are shape, the bar labels are counts.
  await expect(page.locator('[data-pattern-row] [data-layer="shape"][data-status]')).toHaveCount(fixture.patterns.length);
  await expect(page.locator('[data-pattern-list] [data-bar] [data-layer="counts"]')).toHaveCount(
    2 * fixture.patterns.filter((p) => p.bars).length,
  );

  // The "seen more in outliers" rows: in the data's order (never re-sorted), each with the same
  // two bars as its row below when it has them.
  const leadRows = page.locator("[data-lead] a");
  expect(await leadRows.evaluateAll((els) => els.map((e) => e.getAttribute("href")))).toEqual(
    fixture.lead.map((l) => `#${l.anchor}`),
  );
  for (const [i, l] of fixture.lead.entries()) {
    const hasBars = Boolean(fixture.patterns.find((p) => p.anchor === l.anchor)?.bars);
    await expect(leadRows.nth(i).locator("[data-bar]"), l.anchor).toHaveCount(hasBars ? 2 : 0);
  }

  // Banned words and rating numbers in the visible text, with every fold open, and in the text
  // behind every (i) on the page.
  for (const fold of await page.locator("[data-zero-fold] > button").all()) await fold.click();
  const text = await page.locator("body").innerText();
  expect(bannedIn(text)).toEqual([]);
  for (const trigger of await page.locator("main [data-hint-trigger]").all()) {
    const hint = await openHint(page, trigger, phone);
    expect(bannedIn(await hint.innerText())).toEqual([]);
    expect(await wallBreaks(page)).toEqual([]);
    await closeHint(page);
  }

  // Every row: two bars, or the no-comparison line.
  const rows = page.locator("[data-pattern-row]");
  await expect(rows).toHaveCount(fixture.patterns.length);
  for (const row of await rows.all()) {
    const bars = await row.locator("[data-bar]").count();
    const rowText = await row.innerText();
    expect(bars === 2 || rowText.includes(en.patterns.outliersOnly), `row ${await row.getAttribute("data-pattern-row")}`).toBe(true);
  }

  // Order as built, never sorted by a count; no ratio or affinity in a row.
  expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-pattern-row")))).toEqual(EXPECTED_ORDER);
  for (const summary of await page.locator("[data-row-summary]").all()) {
    const t = await summary.innerText();
    expect(t).not.toMatch(/\b(?:affinity|ratio)\b/i);
    expect(t).not.toMatch(/\d(?:\.\d+)?\s*[x×](?![A-Za-z])/);
  }

  // The catalog: fixed order, every kind present.
  expect(await page.locator("[data-catalog] [data-kind]").evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")))).toEqual([
    "all",
    ...KIND_ORDER,
  ]);

  if (info.project.name === "laptop") {
    await expect(page.locator('[data-shell="sidebar"]')).toBeVisible();
    const tree = await page.locator("[data-catalog]").boundingBox();
    const list = await page.locator("[data-pattern-list]").boundingBox();
    expect(tree && list && tree.x + tree.width <= list.x).toBe(true);
  } else {
    await expect(page.locator('[data-shell="tabbar"]')).toBeVisible();
    // Touch rows are 44px.
    const chip = await page.locator('[data-catalog] [data-kind="all"]').boundingBox();
    expect(chip?.height).toBe(44);
  }
  expect(errors).toEqual([]);
});

test("patterns: a row opens its source reels; Rebuild; analysis only", async ({ page }) => {
  const errors = await load(page);
  const first = fixture.patterns.find((p) => !p.zero && p.sources.length)!;
  const row = page.locator(`[data-pattern-row="${first.id}"]`);
  await row.locator("[data-row-summary]").click();
  await expect(row.locator("[data-row-summary]")).toHaveAttribute("aria-expanded", "true");
  // The family (shape) and level (ui) moved from the closed row into the open one.
  const family = row.locator("[data-pattern-family]");
  await expect(family.locator('[data-layer="shape"]')).toHaveText(first.family);
  await expect(family.locator('[data-layer="ui"]')).toHaveText(first.level_tag);
  await expect(row.locator("[data-source]")).toHaveCount(first.sources.length);
  // Plays sit in the source list (counts layer), never in a brain value.
  await expect(row.locator('[data-source] [data-layer="counts"]').first()).toContainText(first.sources[0].counts);
  expect(await wallBreaks(page)).toEqual([]);

  // Analysis only (D31): no Recreate button, no command, no drafts line or draft link, on any row.
  for (const fold of await page.locator("[data-zero-fold] > button").all()) await fold.click();
  for (const r of await page.locator("[data-row-summary]").all()) await r.click();
  await expect(page.locator('[data-job-kind="coach.new_draft"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Recreate" })).toHaveCount(0);
  await expect(page.locator('main a[href^="/lab"]')).toHaveCount(0);
  const text = await page.locator("main").innerText();
  expect(text).not.toMatch(/Recreate|Drafts|strategist\.lab/);
  expect(errors).toEqual([]);

  // Rebuild is a free stage 1 job: in fixtures mode it says so and queues nothing.
  await page.locator('[data-job-kind="patterns.build"]').getByRole("button", { name: en.patterns.rebuild }).click();
  await expect(page.getByRole("status").filter({ hasText: en.jobs.fixturesMode })).toBeVisible();
});

test("patterns: short names, one count per bar", async ({ page }) => {
  const errors = await load(page);
  for (const p of fixture.patterns) {
    const chip = page.locator(`[data-pattern-row="${p.id}"] [data-row-summary] [data-layer="shape"][data-status]`);
    // The chip's hover text is the full name; its visible text is cut to at most 3 words.
    await expect(chip).toHaveAttribute("title", p.label);
    const shown = (await chip.locator("span.truncate").innerText()).replace(/…$/, "");
    expect(shown.split(/\s+/).length, p.label).toBeLessThanOrEqual(3);
    expect(shown.length).toBeLessThanOrEqual(24);
    // Each bar's label is its count alone; the group size is in the bar's name and hover text.
    if (p.bars) {
      const bars = page.locator(`[data-pattern-row="${p.id}"] [data-bar]`);
      await expect(bars.nth(0).locator('[data-layer="counts"]')).toHaveText(String(p.bars.o[0]));
      await expect(bars.nth(1).locator('[data-layer="counts"]')).toHaveText(String(p.bars.m[0]));
      await expect(bars.nth(0)).toHaveAttribute("title", en.patterns.share.replace("{k}", String(p.bars.o[0])).replace("{n}", String(p.bars.o[1])));
    } else {
      // "outliers only" in the row; the full contrast line is its hover text.
      const only = page.locator(`[data-pattern-row="${p.id}"] [data-compare="outliers-only"]`);
      await expect(only).toHaveText(en.patterns.outliersOnly);
      await expect(only).toHaveAttribute("title", new RegExp(en.patterns.noCompare));
    }
  }
  expect(errors).toEqual([]);
});

test("patterns: catalog and label filters", async ({ page }) => {
  const errors = await load(page);
  const visibleIds = () =>
    page.locator("[data-pattern-row]:visible").evaluateAll((els) => els.map((e) => e.getAttribute("data-pattern-row")));
  for (const fold of await page.locator("[data-zero-fold] > button").all()) await fold.click();

  await page.locator('[data-label-toggle] [data-label="suggested"]').click();
  expect(await visibleIds()).toEqual(EXPECTED_ORDER.filter((id) => fixture.patterns.find((p) => p.id === id)!.suggested));

  await page.locator('[data-label-toggle] [data-label="all"]').click();
  await page.locator('[data-catalog] [data-kind="hook"]').click();
  expect(await visibleIds()).toEqual(EXPECTED_ORDER.filter((id) => id.startsWith("hook.")));

  await page.locator('[data-catalog] [data-kind="format"]').click();
  await expect(page.locator("[data-pattern-list]")).toContainText(en.patterns.none);
  expect(errors).toEqual([]);
});

test("patterns: counts said once, group headers match their rows, notes behind the groups (i)", async ({ page }, info) => {
  const errors = await load(page);
  // "n of total" only shows while a filter hides some patterns.
  await expect(page.locator("[data-showing]")).toHaveCount(0);
  await page.locator('[data-label-toggle] [data-label="suggested"]').click();
  await expect(page.locator("[data-showing]")).toBeVisible();
  await page.locator('[data-label-toggle] [data-label="all"]').click();

  // A group header counts only the rows shown under it, never the folded ones.
  for (const tab of fixture.tabs) {
    const rows = fixture.patterns.filter((p) => p.kind === tab.key);
    if (!rows.length) continue;
    const shown = rows.filter((p) => !p.zero).length;
    await expect(page.locator(`[data-group-kind="${tab.key}"] h3`)).toHaveText(shown ? `${tab.label}${shown}` : tab.label);
  }

  // The caveat notes and who is counted are no longer page text; the groups (i) in the list's
  // key row opens to each of them word for word, notes as ui and population as counts.
  for (const line of [...fixture.notes, ...fixture.population]) {
    await expect(page.getByText(line, { exact: true })).toHaveCount(0);
  }
  const trigger = page.locator("[data-pattern-list] [data-list-key] [data-hint-trigger]");
  const hint = await openHint(page, trigger, info.project.name === "phone");
  for (const note of fixture.notes) {
    await expect(hint.locator('[data-note] [data-layer="ui"]').getByText(note, { exact: true })).toBeVisible();
  }
  for (const line of fixture.population) {
    await expect(hint.locator('[data-population] [data-layer="counts"]').getByText(line, { exact: true })).toBeVisible();
  }
  await closeHint(page);
  expect(errors).toEqual([]);
});

for (const scheme of ["light", "dark"] as const) {
  test(`patterns: screenshot ${scheme}`, async ({ page }, info) => {
    const errors = await load(page, scheme);
    const first = fixture.patterns.find((p) => !p.zero && p.sources.length)!;
    await page.locator(`[data-pattern-row="${first.id}"] [data-row-summary]`).click();
    for (const fold of await page.locator("[data-zero-fold] > button").all()) await fold.click();
    await page.mouse.move(0, 0);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: path.resolve(__dirname, `../test-results/shots/patterns-${info.project.name}-${scheme}.png`),
      fullPage: true,
    });
    expect(errors).toEqual([]);
  });
}

// ---------------------------------------------------------------- colour, motion, hints, toggle

/** Resolved colours as [r, g, b, a] 0-255, read through a 1px canvas so rgb(), oklab() and
 *  color-mix() all come back the same way. */
async function colours(page: Page, selector: string): Promise<number[][]> {
  return page.locator(selector).evaluateAll((els) => {
    const c = document.createElement("canvas");
    c.width = c.height = 1;
    const x = c.getContext("2d")!;
    return els.map((el) => {
      x.clearRect(0, 0, 1, 1);
      x.fillStyle = getComputedStyle(el).backgroundColor;
      x.fillRect(0, 0, 1, 1);
      return [...x.getImageData(0, 0, 1, 1).data];
    });
  });
}

/** A colour token from :root, resolved the same way. */
async function token(page: Page, name: string): Promise<number[]> {
  return page.evaluate((n) => {
    const c = document.createElement("canvas");
    c.width = c.height = 1;
    const x = c.getContext("2d")!;
    x.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    x.fillRect(0, 0, 1, 1);
    return [...x.getImageData(0, 0, 1, 1).data];
  }, name);
}

const spread = ([r, g, b]: number[]) => Math.max(r, g, b) - Math.min(r, g, b);

for (const scheme of ["light", "dark"] as const) {
  test(`patterns: outliers are the counts teal, normal is grey (${scheme})`, async ({ page }) => {
    const errors = await load(page, scheme);
    // The list rows and the "seen more in outliers" rows both draw the bars.
    const withBars =
      fixture.patterns.filter((p) => p.bars).length +
      fixture.lead.filter((l) => fixture.patterns.find((p) => p.anchor === l.anchor)?.bars).length;
    const teal = await token(page, "--counts");
    expect(spread(teal), "the counts token is a hue").toBeGreaterThan(60);

    // Every outlier bar and dot is exactly the counts layer's teal (a layer mark, never a
    // status); every normal one is a grey with no hue, so no pair reads as a red/green verdict.
    const oFills = await colours(page, 'main [data-bar-fill="o"]');
    const mFills = await colours(page, 'main [data-bar-fill="m"]');
    expect(oFills).toHaveLength(withBars);
    expect(mFills).toHaveLength(withBars);
    for (const rgba of [...oFills, ...(await colours(page, '[data-group-dot="o"]'))]) {
      expect(rgba.slice(0, 3).every((v, i) => Math.abs(v - teal[i]) <= 2), `teal ${rgba}`).toBe(true);
      expect(rgba[3]).toBe(255);
    }
    for (const rgba of [...mFills, ...(await colours(page, '[data-group-dot="m"]'))]) {
      expect(spread(rgba), `grey ${rgba}`).toBeLessThanOrEqual(12);
      expect(rgba[3]).toBeGreaterThan(0);
    }

    // Text stays ink or muted ink: no value label wears the bar colour.
    const labelColours = await page
      .locator('main [data-bar] [data-layer="counts"]')
      .evaluateAll((els) => els.map((el) => getComputedStyle(el).color));
    expect(labelColours.length).toBe(2 * withBars);
    for (const c of labelColours) expect(c).not.toBe(`rgb(${teal.slice(0, 3).join(", ")})`);
    expect(errors).toEqual([]);
  });
}

test("patterns: bars grow in, counts never move, reduced motion stops it", async ({ page }) => {
  const errors = await load(page);
  // The fills grow from the left (a transform: no box a test measures moves); the normal bar
  // starts one stagger step after the outlier bar.
  const fills = await page.locator("[data-pattern-list] [data-bar-fill]").evaluateAll((els) =>
    els.map((el) => {
      const s = getComputedStyle(el);
      return { group: el.getAttribute("data-bar-fill"), prop: s.transitionProperty, dur: s.transitionDuration, delay: s.transitionDelay };
    }),
  );
  expect(fills.length).toBe(2 * fixture.patterns.filter((p) => p.bars).length);
  for (const f of fills) {
    expect(f.prop).toContain("transform");
    expect(parseFloat(f.dur)).toBeGreaterThan(0.1);
    expect(parseFloat(f.delay) > 0, `delay ${f.group}`).toBe(f.group === "m");
  }
  // Counts are snapshots: no transition and no animation on any counts value.
  const counts = await page.locator('main [data-layer="counts"]').evaluateAll((els) =>
    els.map((el) => {
      const s = getComputedStyle(el);
      return `${s.transitionDuration}|${s.animationName}`;
    }),
  );
  expect(counts.length).toBeGreaterThan(0);
  for (const c of counts) expect(c).toBe("0s|none");
  expect(errors).toEqual([]);

  // Reduced motion: every transition is instant and nothing is left running.
  await page.emulateMedia({ reducedMotion: "reduce" });
  const calm = page;
  const calmErrors = await load(calm);
  const durations = await calm
    .locator("[data-pattern-list] [data-bar-fill], [data-toggle-thumb]")
    .evaluateAll((els) => els.map((el) => parseFloat(getComputedStyle(el).transitionDuration)));
  expect(durations.length).toBeGreaterThan(1);
  for (const d of durations) expect(d).toBeLessThan(0.001);
  await calm.locator('[data-label-toggle] [data-label="suggested"]').click();
  await expect
    .poll(() => calm.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length))
    .toBe(0);
  expect(calmErrors).toEqual([]);
});

test("patterns: every explanation sits behind an (i), word for word", async ({ page }, info) => {
  const errors = await load(page);
  const phone = info.project.name === "phone";
  const about = (topic: string) => en.ui.hintAbout.replace("{topic}", topic);

  // The long lines, the caveat notes and the population are no longer page text.
  for (const line of [en.patterns.lead.note, ...GROUP_HINT_TEXTS]) {
    await expect(page.getByText(line, { exact: true })).toHaveCount(0);
  }

  // No hint icon inside a heading (the group h3 text is matched exactly in another test), and
  // two on the page: the lead's and the groups'.
  await expect(page.locator("main :is(h1, h2, h3) [data-hint-trigger]")).toHaveCount(0);
  await expect(page.locator("main [data-hint-trigger]")).toHaveCount(2);

  // The lead's (i) opens to exactly its note.
  const lead = page.locator("[data-lead] [data-hint-trigger]");
  await expect(lead).toHaveAttribute("aria-label", about(en.patterns.lead.title));
  let hint = await openHint(page, lead, phone);
  await expect(hint).toHaveAttribute("data-layer", "ui");
  await expect(hint).toHaveText(en.patterns.lead.note);
  expect(bannedIn(await hint.innerText())).toEqual([]);
  expect(await wallBreaks(page)).toEqual([]);
  await closeHint(page);

  // The groups' (i), in the list's sticky key row beside the Outliers / Normal swatches, opens
  // to each group's dot, name and definition, then every note, population line and the rest,
  // each word for word.
  const groups = page.locator("[data-pattern-list] [data-list-key] [data-hint-trigger]");
  await expect(groups).toHaveAttribute("aria-label", en.patterns.legend.more);
  hint = await openHint(page, groups, phone);
  await expect(hint).toHaveAttribute("data-layer", "ui");
  for (const [group, name, def] of [
    ["outliers", en.patterns.legend.outliers, en.patterns.legend.outliersDef],
    ["normal", en.patterns.legend.normal, en.patterns.legend.normalDef],
  ] as const) {
    const row = hint.locator(`[data-group="${group}"]`);
    await expect(row.locator("[data-group-dot]")).toHaveCount(1);
    await expect(row.getByText(name, { exact: true })).toBeVisible();
    await expect(row.locator("[data-group-def]")).toHaveText(def);
  }
  for (const line of GROUP_HINT_TEXTS) await expect(hint.getByText(line, { exact: true })).toBeVisible();
  expect(bannedIn(await hint.innerText())).toEqual([]);
  expect(await wallBreaks(page)).toEqual([]);
  await closeHint(page);
  expect(errors).toEqual([]);
});

test("patterns: the label toggle slides to the pick and keeps its tap size", async ({ page }, info) => {
  const errors = await load(page);
  const toggle = page.locator("[data-label-toggle]");
  const thumb = toggle.locator("[data-toggle-thumb]");
  const onPick = async (key: string) => {
    const [t, b] = await Promise.all([thumb.boundingBox(), toggle.locator(`[data-label="${key}"]`).boundingBox()]);
    return Boolean(t && b && Math.abs(t.x - b.x) <= 1.5 && Math.abs(t.width - b.width) <= 1.5);
  };
  await expect(toggle).toHaveAttribute("data-thumb", /^(placed|ready)$/);
  await expect.poll(() => onPick("all")).toBe(true);
  for (const key of ["suggested", "accepted", "all"]) {
    await toggle.locator(`[data-label="${key}"]`).click();
    await expect(toggle.locator(`[data-label="${key}"]`)).toHaveAttribute("aria-pressed", "true");
    await expect(toggle.locator('[aria-pressed="true"]')).toHaveCount(1);
    await expect.poll(() => onPick(key)).toBe(true);
  }
  // The two options after All carry their chip's mark (filled, outlined accent; from 640px).
  await expect(toggle.locator("[data-chip-mark]")).toHaveCount(2);
  // "All" is never cut short, at any width.
  const allCut = await toggle
    .locator('[data-label="all"] > span')
    .first()
    .evaluate((el) => el.scrollWidth > el.clientWidth);
  expect(allCut).toBe(false);
  if (info.project.name === "phone") {
    expect((await toggle.boundingBox())?.height).toBe(44);
  }
  expect(errors).toEqual([]);
});
