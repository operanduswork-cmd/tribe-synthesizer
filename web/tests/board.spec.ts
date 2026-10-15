// Board screen in fixtures mode, at phone (390x844) and laptop (1280x800) widths: no console
// errors, no sideways page scroll, the licence footer, the D20 wall in the DOM (no counts value
// shares its closest line with a brain value), no banned words in the visible text (the list is
// strategist's own: dashboard/render.py find_banned, called through Python), and the board
// rules: sort options are exactly the page's allowed keys, no rank numbers, the TRIBE column is
// never sorted by a brain value (a yes/no pin is allowed, D32), and the peek shows no brain value. Round 2 (colour + motion + hints): each
// header tag, filter field and chip leads with its layer's dot in that layer's colour while text
// stays ink; the TRIBE yes / no keeps its exact text with the split brain dot behind the wall only;
// row hover changes the background only (36px, no move); the creators note opens from an (i)
// hint; the peek's strip marks this reel in counts teal; reduced motion leaves nothing running.
// Round 3 (D30, less text): no subtitle, stamp, "Page built" line or menu notes; the counts note
// opens from the (i) next to the title (exactly en.board.footnote); the strip's legend opens from
// its own (i), still never teal; table and card flags show their heads, the peek the full labels.
// Round 4 (D31, analysis only): the peek has no Recreate command; Flags and Format are hidden by
// default (still in the Fields menu); no "(18 reels)" note or other sub-text in a row.
// Saves light and dark screenshots to test-results/shots/board-<project>-<scheme>.png.

import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import en from "../copy/en.json";
import board from "../fixtures/board.json";

const ROOT = path.resolve(__dirname, "..", "..");
const SHOTS = path.resolve(__dirname, "..", "test-results", "shots");

// The closest "line" around a value: a marked line, a table row, a list item or a paragraph.
const LINE = "[data-line], tr, [role=row], [role=menuitemradio], li, p, h1, h2, h3, h4";

type RuleResult = { banned: string[]; mixed: string[]; brain: string[]; probe: string[] };

/** Run strategist's own rule checks (dashboard/render.py) on the page text. Read-only. */
function rules(text: string, lines: string[] = [], brainText = ""): RuleResult {
  const code = [
    "import json, sys",
    "from strategist import store",
    "R = store.rules()",
    "d = json.load(sys.stdin)",
    "mixed = []",
    "for line in d['lines']:",
    "    try:",
    "        R.check_mixed_layers([('line', line)])",
    "    except R.RenderError as e:",
    "        mixed.append(str(e))",
    "print(json.dumps({'banned': R.find_banned(d['text']), 'mixed': mixed,",
    "    'brain': R.BRAIN_TERMS_RE.findall(d['brain']), 'probe': R.find_banned(' '.join(['vir' + 'al', 'vie' + 'ws']))}))",
  ].join("\n");
  const out = execFileSync("python", ["-c", code], {
    cwd: ROOT,
    input: JSON.stringify({ text, lines, brain: brainText }),
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    encoding: "utf-8",
  });
  return JSON.parse(out) as RuleResult;
}

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function openBoard(page: Page) {
  await page.goto("/board");
  await expect(page.locator('[data-board="view"]')).toBeVisible();
  await page.waitForLoadState("networkidle");
}

/** Lines (by the LINE rule) where a counts value and a brain value meet. */
async function wallBreaks(page: Page): Promise<string[]> {
  return page.evaluate((LINE) => {
    const lineOf = (el: Element) => el.closest(LINE) ?? document.body;
    const counts = new Set(Array.from(document.querySelectorAll('[data-layer="counts"]'), lineOf));
    return Array.from(document.querySelectorAll('[data-layer="brain"]'))
      .map(lineOf)
      .filter((l) => counts.has(l))
      .map((l) => (l as HTMLElement).outerHTML.slice(0, 160));
  }, LINE);
}

async function lineTexts(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("#main [data-line], #main tr"), (el) => (el as HTMLElement).innerText.replace(/\s+/g, " ").trim()).filter(Boolean),
  );
}

async function openPeek(page: Page, isPhone: boolean) {
  if (isPhone) {
    // The handle is the card's only button (named by peekAt); its ::after covers the card.
    await page.locator('[data-board="cards"] > li').first().getByRole("button").click();
  } else {
    await page.locator('[data-board="table"] tr[data-line="reel"]').first().locator("td").first().getByRole("button").click();
  }
  const peek = page.locator('[data-board="peek"]');
  await expect(peek).toBeVisible();
  return peek;
}

test("board: layout, footer, wall, words and no row numbers", async ({ page }, info) => {
  const isPhone = info.project.name === "phone";
  const errors = watchErrors(page);
  await openBoard(page);

  // Licence footer (LICENCE 12) on the page.
  const footer = page.locator("footer[data-licence]");
  await expect(footer).toContainText(en.footer.llama);
  await expect(footer).toContainText("CC BY-NC 4.0");

  // No sideways page scroll.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  // Every reel is on the board, as table rows on a laptop and cards on a phone.
  if (isPhone) {
    await expect(page.locator('[data-board="table"]')).toBeHidden();
    await expect(page.locator('[data-board="cards"] > li')).toHaveCount(board.reels.length);
    const card = page.locator('[data-board="cards"] > li').first();
    const box = await card.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    // The whole card is the tap target: a tap away from the handle (near the bottom-right
    // corner) opens the peek too. Esc closes it again before the checks below.
    await card.click({ position: { x: (box?.width ?? 0) - 12, y: (box?.height ?? 0) - 12 } });
    const peek = page.locator('[data-board="peek"]');
    await expect(peek).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(peek).toHaveCount(0);
  } else {
    await expect(page.locator('[data-board="table"]')).toBeVisible();
    await expect(page.locator('[data-board="table"] tr[data-line="reel"]')).toHaveCount(board.reels.length);
    const rowH = await page.locator('[data-board="table"] tr[data-line="reel"]').first().boundingBox();
    expect(rowH?.height).toBe(36);
    // The brain column's rows line up with the main rows.
    const brainH = await page.locator('[data-board="tribe-column"] tr[data-line="reel-brain"]').first().boundingBox();
    expect(brainH?.y).toBe(rowH?.y);
    expect(brainH?.height).toBe(rowH?.height);
    // Column headers carry their layer tag in mono (Neon).
    await expect(page.locator('[data-board="table"] thead [data-tag-layer="counts"]').first()).toBeVisible();
    await expect(page.locator('[data-board="tribe-column"] thead [data-tag-layer="brain"]')).toBeVisible();
  }

  // The D20 wall: no counts value shares its closest line with a brain value.
  expect(await wallBreaks(page)).toEqual([]);
  // ...nor a card: a card holds counts, so the TRIBE yes/no stays in the table's own column.
  const mixedCards = await page
    .locator('[data-board="cards"] > li')
    .evaluateAll((cards) => cards.filter((c) => c.querySelector('[data-layer="counts"]') && c.querySelector('[data-layer="brain"]')).length);
  expect(mixedCards).toBe(0);
  await expect(page.locator('[data-layer="counts"] [data-layer="brain"], [data-layer="brain"] [data-layer="counts"]')).toHaveCount(0);

  // TRIBE values on the board are the word "yes" on every row (his D32 override); the dot or ring tells real reads apart.
  const brainValues = await page.locator('#main [data-layer="brain"]').allInnerTexts();
  expect(brainValues.length).toBeGreaterThan(0);
  for (const v of brainValues) expect(v.trim()).toBe("yes");

  // No row numbers: no row or card starts with a bare number, no ordered list of reels.
  const firsts = await page.evaluate(() =>
    [
      ...Array.from(document.querySelectorAll('[data-board="table"] tr[data-line="reel"] td:first-child')),
      ...Array.from(document.querySelectorAll('[data-board="cards"] [data-line="title"]')),
    ].map((el) => (el as HTMLElement).textContent?.trim() ?? ""),
  );
  expect(firsts.length).toBeGreaterThan(0);
  for (const f of firsts) expect(f).not.toMatch(/^#?\d+[.)]?(\s|$)/);
  await expect(page.locator("#main ol li[data-sc]")).toHaveCount(0);

  // Banned words (strategist's list) in the visible text, and no line names counts and brain.
  const text = await page.evaluate(() => document.body.innerText);
  const r = rules(text, await lineTexts(page));
  expect(r.probe.length, "the strategist ban list loaded").toBeGreaterThan(0);
  expect(r.banned).toEqual([]);
  expect(r.mixed).toEqual([]);
  expect(text).not.toMatch(/\bviews\b/i);

  expect(errors).toEqual([]);
});

test("board: default fields hide Flags and Format, no sub-text in a row", async ({ page }, info) => {
  await openBoard(page);
  const isPhone = info.project.name === "phone";
  const notes = board.reels.map((r) => r.cells.x.split(" (")[1]).filter(Boolean).map((n) => `(${n}`);
  const scope = page.locator(isPhone ? '[data-board="cards"]' : '[data-board="table"]');
  const text = await scope.innerText();
  for (const n of notes) expect(text).not.toContain(n);
  if (!isPhone) {
    const heads = await page.locator('[data-board="table"] thead th').allInnerTexts();
    for (const hidden of [en.board.columns.flags, en.board.columns.format]) expect(heads.join("|")).not.toContain(hidden);
  }
  // The full x text stays reachable on hover.
  const withNote = board.reels.find((r) => r.cells.x.includes(" ("))!;
  await expect(scope.locator(`[title="${withNote.cells.x}"]`).first()).toHaveCount(1);
});

test("board: sort options are the page's allowed keys only", async ({ page }) => {
  await openBoard(page);
  await page.locator('[data-board="sort"]').click();
  const menu = page.locator('[data-board="sort-menu"]');
  await expect(menu).toBeVisible();
  const keys = await menu.locator("[data-sort-key]").evaluateAll((els) => els.map((e) => e.getAttribute("data-sort-key")));
  expect(keys).toEqual(board.sorts.map((s) => s.key));
  for (const k of keys) expect(k).not.toMatch(/tribe|brain|peak|flat|high/i);
  const labels = await menu.locator("[data-sort-key]").allInnerTexts();
  expect(labels.map((l) => l.trim())).toEqual(board.sorts.map((s) => s.label));
  // No explanation note under the options (D30).
  await expect(menu.locator("p")).toHaveCount(0);
  // Picking one re-orders the reels by that key. The button names the sort (name and hover
  // text) and shows only "Sort" (D30).
  await menu.locator('[data-sort-key="-plays"]').click();
  const sort = page.locator('[data-board="sort"]');
  await expect(sort).toHaveAttribute("aria-label", /plays, most first/);
  await expect(sort).toHaveAttribute("title", /plays, most first/);
  expect((await sort.innerText()).trim()).not.toContain("plays");
});

test("board: less text, the counts note opens from the title's (i)", async ({ page }, info) => {
  const isPhone = info.project.name === "phone";
  const errors = watchErrors(page);
  await openBoard(page);
  // Gone from the page's visible text (D30): the subtitle, the stamp, the "Page built" line and
  // the counts note (the shell's own freshness lines are the shell spec's).
  const text = await page.locator("#main").innerText();
  const subtitle = (en.pages.board as Record<string, string | undefined>).subtitle;
  for (const gone of [subtitle, board.stamp[0], en.board.footnote]) {
    if (gone) expect(text).not.toContain(gone);
  }
  await expect(page.locator('[data-line="footnote"]')).toHaveCount(0);

  // The title stays exactly the page name; the (i) sits next to it, not inside the h1.
  const header = page.locator('[data-board="header"]');
  await expect(header.locator("h1")).toHaveText(en.pages.board.title);
  await expect(header.locator("h1 button")).toHaveCount(0);
  const trigger = header.getByRole("button", { name: en.ui.hintAbout.replace("{topic}", en.pages.board.title), exact: true });
  await expect(trigger).toBeVisible();
  if (isPhone) {
    // 44px hit area on touch (the 16px icon keeps its look; tap-target's ::before).
    const hit = await trigger.evaluate((el) => {
      const cs = getComputedStyle(el, "::before");
      return cs.content !== "none" && cs.position === "absolute" ? parseFloat(cs.height) : el.getBoundingClientRect().height;
    });
    expect(hit).toBeGreaterThanOrEqual(44);
    await trigger.tap();
  } else {
    await trigger.click();
  }
  const hint = page.locator("[data-hint]");
  await expect(hint).toBeVisible();
  await expect(hint).toHaveText(en.board.footnote);
  await expect(hint).toHaveAttribute("data-layer", "ui");
  expect(rules(await hint.innerText()).banned).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(hint).toHaveCount(0);

  // Round 4 text cut: Flags and Format are hidden by default; the Fields menu still has both.
  await expect(page.locator('[data-board="table"] thead th:has-text("' + en.board.columns.flags + '")')).toHaveCount(0);
  await expect(page.locator("[data-flag]")).toHaveCount(0);
  await page.locator('[data-board="fields"]').click();
  const fieldsMenu = page.locator('[data-board="fields-popover"]');
  await expect(fieldsMenu.locator('[data-column="flags"]')).toHaveAttribute("aria-checked", "false");
  await expect(fieldsMenu.locator('[data-column="format"]')).toHaveAttribute("aria-checked", "false");
  await fieldsMenu.locator('[data-column="flags"]').click();
  await page.keyboard.press("Escape");

  // With Flags on, table and card flags show their heads only; the hover text keeps the full labels.
  const reel = board.reels.find((r) => r.badges.some((b) => / · |: |, /.test(b.label)))!;
  const long = reel.badges.find((b) => / · |: |, /.test(b.label))!;
  const scope = isPhone ? page.locator(`[data-board="cards"] > li[data-sc="${reel.sc}"]`) : page.locator(`[data-board="table"] tr[data-sc="${reel.sc}"]`);
  const flags = await scope.locator("[data-flag]").allInnerTexts();
  for (const f of flags) expect(f).not.toMatch(/ · |: |, /);
  if (isPhone) expect(flags).toContain(long.label.split(/ · |: |, /)[0]);
  await expect(scope.locator(`[title="${reel.cells.flags}"]`)).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("board: default order pins read reels first, longest clip first; a sort key drops the pin", async ({ page }, info) => {
  test.skip(info.project.name !== "laptop", "the table is a laptop layout");
  await openBoard(page);
  const byLength = (a: (typeof board.reels)[number], b: (typeof board.reels)[number]) => (b.sort.duration ?? -1) - (a.sort.duration ?? -1);
  const read = board.reels.filter((r) => r.cells.tribe === "yes").sort(byLength);
  const rest = board.reels.filter((r) => r.cells.tribe !== "yes").sort(byLength);
  // The TRIBE column's twin rows follow the main table's inside the same wrapper: take the main ones.
  const rows = page.locator('[data-board="table"] tbody tr[data-sc]');
  const order = () => rows.evaluateAll((els, n) => els.slice(0, n).map((e) => e.getAttribute("data-sc")), board.reels.length);
  expect(await order()).toEqual([...read, ...rest].map((r) => r.sc));
  // Same order on the TRIBE column's twin rows, and no rank numbers anywhere.
  await expect(page.locator('[data-board="tribe-column"] tbody tr[data-sc]').first()).toHaveAttribute("data-sc", [...read, ...rest][0].sc);

  // Picking a key from the menu removes the pin: plays order, whatever the read flag says.
  await page.locator('[data-board="sort"]').click();
  await page.locator('[data-sort-key="-plays"]').click();
  const plays = [...board.reels].sort((a, b) => (b.sort.plays ?? -1) - (a.sort.plays ?? -1));
  expect(await order()).toEqual(plays.map((r) => r.sc));
});

test("board: TRIBE column is never sortable and can be hidden", async ({ page }, info) => {
  test.skip(info.project.name !== "laptop", "the table is a laptop layout");
  await openBoard(page);
  const brain = page.locator('[data-board="tribe-column"]');
  await expect(brain).toBeVisible();
  await expect(brain.locator("th button, th [role=button]")).toHaveCount(0);
  await expect(brain.locator("th")).not.toHaveAttribute("aria-sort", /.+/);
  // Sortable headers are exactly the sort fields the page allows.
  const sortable = await page.locator('[data-board="table"] thead th button').count();
  expect(sortable).toBeLessThanOrEqual(board.sorts.length);

  // Fields popover (Dovetail): switch the TRIBE column off.
  await page.locator('[data-board="fields"]').click();
  await page.locator('[data-board="fields-popover"] [data-column="tribe"]').click();
  await expect(brain).toHaveCount(0);
});

test("board: filter chip and saved view", async ({ page }, info) => {
  await openBoard(page);
  await page.locator('[data-board="filters"]').click();
  await page.getByRole("menuitem", { name: en.board.filters.fields.hook }).click();
  await page.getByRole("menuitemradio", { name: board.options.hook[1] }).click();
  const chip = page.locator('[data-filter-chip="hook"]');
  await expect(chip).toContainText(board.options.hook[1]);
  if (info.project.name === "phone") {
    // Touch targets: the chip's remove button, "Add filter" and "Clear" are 44px tall on a phone.
    const chips = page.locator('[data-board="chips"]');
    const targets = [
      chip.getByRole("button"),
      chips.getByRole("button", { name: en.board.filters.add, exact: true }),
      chips.getByRole("button", { name: en.board.filters.clear, exact: true }),
    ];
    for (const target of targets) {
      await expect(target).toBeVisible();
      expect((await target.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    }
  }
  await expect(page.locator('[data-board="count"]')).toHaveText(`1 of ${board.reels.length} reels`);
  await expect(page.locator('[data-board="view-pill"]')).toContainText(en.board.views.custom);
  await chip.getByRole("button").click();
  await expect(chip).toHaveCount(0);
  await expect(page.locator('[data-board="view-pill"]')).toContainText(en.board.views.all);
});

test("board: peek shows no brain value and opens the reel", async ({ page }, info) => {
  const isPhone = info.project.name === "phone";
  const errors = watchErrors(page);
  await openBoard(page);
  const peek = await openPeek(page, isPhone);

  await expect(peek.locator("[data-layer=brain]")).toHaveCount(0);
  const peekText = await peek.innerText();
  const r = rules(peekText, [], peekText);
  expect(r.banned).toEqual([]);
  expect(r.brain, "no brain words in the peek").toEqual([]);
  expect(peekText).not.toMatch(/TRIBE/);
  // Analysis only (D31): no Recreate section or command in the peek.
  expect(peekText).not.toMatch(/Recreate|strategist\.lab|python -m/);
  expect(await wallBreaks(page)).toEqual([]);

  if (!isPhone) {
    expect((await peek.boundingBox())?.width).toBe(420);
    await expect(peek.locator('[data-board="peek-open"]')).toContainText(en.board.peek.open);
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  // Esc closes; Ctrl+Enter opens the reel page (default sort puts DEMO0000001 first).
  await page.keyboard.press("Escape");
  await expect(peek).toHaveCount(0);
  if (!isPhone) {
    await openPeek(page, false);
    await page.keyboard.press("Control+Enter");
    await expect(page).toHaveURL(/\/reels\/DEMO0000001$/);
  }
  expect(errors).toEqual([]);
});

/** The given colour tokens (CSS custom properties) as computed rgb() strings. */
async function tokens(page: Page, names: string[]): Promise<Record<string, string>> {
  return page.evaluate((names) => {
    const probe = document.createElement("span");
    document.body.appendChild(probe);
    const out: Record<string, string> = {};
    for (const n of names) {
      probe.style.color = `var(--${n})`;
      out[n] = getComputedStyle(probe).color;
    }
    probe.remove();
    return out;
  }, names);
}

const MARKS = ["counts", "shape", "brain-cool", "brain-warm"];

test("board: layer colour dots, the TRIBE mark and row hover", async ({ page }, info) => {
  test.skip(info.project.name !== "laptop", "the table is a laptop layout");
  const errors = watchErrors(page);
  await openBoard(page);
  const table = page.locator('[data-board="table"]');
  const tribe = page.locator('[data-board="tribe-column"]');
  const tok = await tokens(page, MARKS);

  // Every header tag leads with its own layer's dot, in that layer's colour (counts teal, shape
  // indigo, brain split cool/warm); the tag text itself never wears a layer colour.
  const tags = await page.locator('[data-board="table"] thead [data-tag-layer], [data-board="tribe-column"] thead [data-tag-layer]').evaluateAll((els) =>
    els.map((e) => {
      const dot = e.querySelector("[data-layer-dot]");
      return {
        layer: e.getAttribute("data-tag-layer"),
        dot: dot?.getAttribute("data-layer-dot") ?? null,
        fills: dot ? Array.from(dot.querySelectorAll("circle, path"), (s) => getComputedStyle(s).fill).filter((f) => f !== "none") : [],
        text: getComputedStyle(e).color,
      };
    }),
  );
  expect(new Set(tags.map((t) => t.layer))).toEqual(new Set(["facts", "counts", "shape", "brain"]));
  for (const t of tags) {
    expect(t.dot, `dot of the ${t.layer} tag`).toBe(t.layer);
    if (t.layer === "counts") expect(t.fills).toEqual([tok.counts]);
    if (t.layer === "shape") expect(t.fills).toEqual([tok.shape]);
    if (t.layer === "brain") expect(t.fills).toEqual([tok["brain-cool"], tok["brain-warm"]]);
    expect(Object.values(tok)).not.toContain(t.text);
  }

  // TRIBE: every row says "yes"; a real read leads with the brain's split dot, no read with an empty ring; the value text
  // is exactly yes, holds no mark itself, and is never drawn in a layer colour (not a status).
  const yes = board.reels.filter((r) => r.cells.tribe === "yes").length;
  expect(yes).toBeGreaterThan(0);
  await expect(tribe.locator('tbody [data-tribe="yes"] [data-layer-dot="brain"]')).toHaveCount(yes);
  await expect(tribe.locator('tbody [data-tribe="no"] [data-layer-dot]')).toHaveCount(0);
  await expect(tribe.locator('tbody [data-tribe="no"] svg')).toHaveCount(board.reels.length - yes);
  await expect(tribe.locator('[data-layer="brain"] svg')).toHaveCount(0);
  const values = await tribe
    .locator('tbody [data-layer="brain"]')
    .evaluateAll((els) => els.map((e) => ({ text: (e as HTMLElement).innerText.trim(), color: getComputedStyle(e).color })));
  // Every row's text is "yes" (his override, D32); the dot (real read) or ring (no read) tells them apart.
  expect(values.map((v) => v.text)).toEqual(board.reels.map(() => "yes"));
  for (const v of values) expect(Object.values(tok)).not.toContain(v.color);
  // No mark of any layer in the main rows (D20): the split dot lives behind the wall only.
  await expect(table.locator('tr[data-line="reel"] [data-layer-dot]')).toHaveCount(0);
  await expect(tribe.locator('tr[data-line="reel-brain"] [data-layer-dot="brain"]')).toHaveCount(yes);

  // Hover changes the background only: both halves of the row light up together, and the row
  // keeps its place and its 36px height (no lift, no grow).
  const row = table.locator('tr[data-line="reel"]').nth(1);
  const sc = await row.getAttribute("data-sc");
  const twin = tribe.locator(`tr[data-sc="${sc}"]`);
  const bg = (l: typeof row) => l.evaluate((el) => getComputedStyle(el).backgroundColor);
  const before = await bg(row);
  const boxBefore = await row.boundingBox();
  await row.locator("td").nth(2).hover();
  await expect.poll(() => bg(row)).not.toBe(before);
  await expect.poll(async () => (await bg(twin)) === (await bg(row))).toBe(true);
  expect(await row.boundingBox()).toEqual(boxBefore);
  expect(boxBefore?.height).toBe(36);
  expect(await row.evaluate((el) => getComputedStyle(el).transform)).toBe("none");
  await page.mouse.move(2, 2);
  await expect.poll(() => bg(row)).toBe(before);

  expect(await wallBreaks(page)).toEqual([]);
  expect(errors).toEqual([]);
});

test("board: filter chips and the Filters menu carry their layer's dot", async ({ page }) => {
  await openBoard(page);
  await page.locator('[data-board="filters"]').click();
  const fields = await page
    .locator("[data-filter-field]")
    .evaluateAll((els) => els.map((e) => ({ field: e.getAttribute("data-filter-field"), dot: e.querySelector("[data-layer-dot]")?.getAttribute("data-layer-dot") ?? null })));
  const LAYER: Record<string, string> = { hook: "shape", format: "shape", length: "facts", flag: "counts", twoX: "counts", labels: "shape", tribe: "brain" };
  expect(fields.length).toBe(Object.keys(LAYER).length);
  for (const f of fields) expect(f.dot, `dot of the ${f.field} filter`).toBe(LAYER[f.field ?? ""]);
  // The TRIBE chip carries the brain mark in its own group behind the dotted rule, never on the
  // line that holds the counts and shape chips (D20).
  await page.getByRole("menuitem", { name: en.board.filters.fields.tribe }).click();
  await page.getByRole("menuitemradio", { name: en.board.filters.yes, exact: true }).click();
  await expect(page.locator('[data-line="filters-brain"] [data-filter-chip="tribe"] [data-layer-dot="brain"]')).toHaveCount(1);
  await expect(page.locator('[data-line="filters"] [data-layer-dot="brain"]')).toHaveCount(0);
  expect(await wallBreaks(page)).toEqual([]);
});

test("board: the creators note sits behind an (i) hint", async ({ page }, info) => {
  const isPhone = info.project.name === "phone";
  const errors = watchErrors(page);
  await openBoard(page);
  const creators = page.locator('[data-board="creators"]');
  const toggle = creators.locator('[data-board="creators-toggle"]');
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  // The note is no longer a line of text on the page.
  expect(await page.evaluate(() => document.body.innerText)).not.toContain(en.board.creators.body);

  const trigger = creators.getByRole("button", { name: en.ui.hintAbout.replace("{topic}", en.board.creators.title), exact: true });
  await expect(trigger).toBeVisible();
  if (isPhone) {
    // 44px hit area on touch (the 16px icon keeps its look; tap-target's ::before).
    const hit = await trigger.evaluate((el) => {
      const cs = getComputedStyle(el, "::before");
      return cs.content !== "none" && cs.position === "absolute" ? parseFloat(cs.height) : el.getBoundingClientRect().height;
    });
    expect(hit).toBeGreaterThanOrEqual(44);
    await trigger.tap();
  } else {
    await trigger.click();
  }
  const hint = page.locator("[data-hint]");
  await expect(hint).toBeVisible();
  await expect(hint).toHaveText(en.board.creators.body);
  await expect(hint).toHaveAttribute("data-layer", "ui");
  // The hint is its own control: pressing it does not open the fold.
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(rules(await hint.innerText()).banned).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(hint).toHaveCount(0);

  // The header row opens the fold; the creators' counts lines then show.
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(creators.locator('li[data-layer="counts"]').first()).toBeVisible();
  await expect(creators.locator("[data-layer=brain]")).toHaveCount(0);
  await expect(creators.locator("[data-layer-dot=brain]")).toHaveCount(0);
  expect(await wallBreaks(page)).toEqual([]);
  expect(errors).toEqual([]);
});

test("board: the peek's own-reels strip marks this reel in counts teal", async ({ page }, info) => {
  await openBoard(page);
  const peek = await openPeek(page, info.project.name === "phone");
  const strip = peek.locator('[data-line="peer"]');
  await expect(strip).toBeVisible();
  const tok = await tokens(page, MARKS);
  expect(await strip.locator('[data-peer="me"]').evaluate((el) => getComputedStyle(el).fill)).toBe(tok.counts);
  // The legend is no line under the strip any more (D30): it is the strip's name, and the (i) at
  // its end opens to exactly it, in the counts layer.
  const legend = await strip.locator("svg[role=img]").getAttribute("aria-label");
  expect(board.reels.map((r) => r.peer?.label)).toContain(legend);
  expect(await strip.innerText()).not.toContain(legend ?? "");
  const trigger = strip.getByRole("button", { name: en.board.peek.stripHint, exact: true });
  if (info.project.name === "phone") {
    const hit = await trigger.evaluate((el) => {
      const cs = getComputedStyle(el, "::before");
      return cs.content !== "none" && cs.position === "absolute" ? parseFloat(cs.height) : el.getBoundingClientRect().height;
    });
    expect(hit).toBeGreaterThanOrEqual(44);
    await trigger.tap();
  } else {
    await trigger.click();
  }
  const hint = page.locator("[data-hint]");
  await expect(hint).toHaveText(legend ?? "");
  await expect(hint).toHaveAttribute("data-layer", "counts");
  // Only the dot is teal: the ticks, the median and the legend stay ink or muted.
  const others = [
    ...(await strip.evaluate((el) => Array.from(el.querySelectorAll('[data-peer="tick"], [data-peer="median"]'), (s) => getComputedStyle(s).stroke))),
    await hint.evaluate((el) => getComputedStyle(el).color),
  ];
  expect(others.length).toBeGreaterThan(2);
  for (const c of others) expect(Object.values(tok)).not.toContain(c);
  // Esc closes the legend and leaves the peek open.
  await page.keyboard.press("Escape");
  await expect(hint).toHaveCount(0);
  await expect(peek).toBeVisible();
  // Still no brain value or brain mark in the peek (D20, D21).
  await expect(peek.locator("[data-layer=brain]")).toHaveCount(0);
  await expect(peek.locator("[data-layer-dot=brain]")).toHaveCount(0);
});

test("board: reduced motion leaves nothing animating", async ({ page }, info) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openBoard(page);
  await openPeek(page, info.project.name === "phone");
  await expect
    .poll(() => page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length), { timeout: 2000 })
    .toBe(0);
  const seconds = await page.locator('[data-board="peek"]').evaluate((el) => parseFloat(getComputedStyle(el).animationDuration) || 0);
  expect(seconds).toBeLessThanOrEqual(0.001);
});

for (const scheme of ["light", "dark"] as const) {
  test(`board screenshot ${scheme}`, async ({ page }, info) => {
    await page.emulateMedia({ colorScheme: scheme });
    await openBoard(page);
    await page.screenshot({ path: path.join(SHOTS, `board-${info.project.name}-${scheme}.png`), fullPage: true });
    await openPeek(page, info.project.name === "phone");
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(SHOTS, `board-${info.project.name}-${scheme}-peek.png`) });
  });
}
