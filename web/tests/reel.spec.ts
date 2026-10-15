// The reel screen in fixtures mode, at phone (390x844) and laptop (1280x800) widths: no console
// errors, no sideways scroll, the licence footer, the D20 wall (no counts value shares a row with
// a brain value; every chart has one owner layer and never holds the other: counts in the counts
// chart, brain in the timeline, the 3D brain and the Areas tab; the reel video, D30, holds
// neither), the wording rules
// (dashboard/render.py find_banned, run in Python so the list is never copied), the card shown
// exactly as precomputed, disabled stage 2 and 3 buttons, the laptop command, the playhead, and a
// free button that says fixtures mode. Round 3 (D30, less text): every explanation, caveat and
// credit that left the page opens from its (i) word for word (the card footnote, the notes on the
// read, the colour key, the HCP and atlas credits, the facts stamps and the wall sentence), the
// legends are swatches whose names show on hover or tap, and the laptop commands sit behind one
// lock button. Screenshots go to test-results/shots/reel-*.png.

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import jobKinds from "../contracts/job-kinds.json";
import en from "../copy/en.json";
import board from "../fixtures/board.json";
import factsReel from "../fixtures/more/reel-DEMO0000002.json";
import reel from "../fixtures/reel.json";
import tribe from "../fixtures/tribe.json";

const URL = `/reels/${reel.shortcode}`;
const ROOT = path.resolve(__dirname, "..", "..");
const SHOTS = path.resolve(__dirname, "..", "test-results", "shots");
const EM_DASH = String.fromCharCode(0x2014);
const ROW = "[data-row], li, tr, p, dt, dd, h1, h2, h3, figcaption, [role=row]";
const FIND_BANNED =
  "import json, sys\nsys.path.insert(0, '.')\nfrom dashboard.render import find_banned\nprint(json.dumps(find_banned(sys.stdin.read())))";

/** Banned words and rating numbers in a text, by the same check the pages run (D20). */
function banned(text: string): string[] {
  const out = execFileSync("python", ["-c", FIND_BANNED], {
    cwd: ROOT,
    input: text,
    encoding: "utf8",
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  return JSON.parse(out) as string[];
}

/** Counts and brain values that share a row or line container, or sit inside each other. */
async function wallBreaks(page: Page): Promise<string[]> {
  return page.evaluate((rowSel) => {
    const main = document.querySelector("main")!;
    const out: string[] = [];
    const pairs: Array<[string, string]> = [
      ["counts", "brain"],
      ["brain", "counts"],
    ];
    for (const [mine, other] of pairs) {
      for (const el of main.querySelectorAll(`[data-layer="${mine}"]`)) {
        const row = el.closest(rowSel) ?? el.parentElement;
        if (el.closest(`[data-layer="${other}"]`) || row?.querySelector(`[data-layer="${other}"]`)) {
          out.push(`${mine} "${(el.textContent ?? "").slice(0, 40)}" shares a row with ${other}`);
        }
      }
    }
    return out;
  }, ROW);
}

async function noSidewaysScroll(page: Page) {
  const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll).toBeLessThanOrEqual(width);
}

async function checkText(page: Page) {
  const text = await page.locator("main").innerText();
  expect(banned(text)).toEqual([]);
  expect(text).not.toMatch(/(?<![A-Za-z])LOW(?![A-Za-z])/);
  expect(text).not.toContain(EM_DASH);
}

/** Every chart on the page: its owner layer has values, the other layer none, and no chart sits
 *  inside another (D20). The 3D brain and the Areas tab are brain charts (D28). The reel video
 *  (D30) owns neither layer: it holds no counts and no brain values at all. */
const OWN = { counts: "counts", timeline: "brain", brain: "brain", areas: "brain", video: null } as const;

async function chartOwners(page: Page): Promise<string[]> {
  const charts = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("[data-chart]")].map((c) => ({
      name: c.dataset.chart ?? "",
      counts: c.querySelectorAll('[data-layer="counts"]').length,
      brain: c.querySelectorAll('[data-layer="brain"]').length,
      nested: c.parentElement?.closest("[data-chart]") !== null,
    })),
  );
  for (const c of charts) {
    expect(c.nested).toBe(false);
    expect(c.name in OWN, `chart "${c.name}" has no owner layer`).toBe(true);
    const own = OWN[c.name as keyof typeof OWN];
    if (own === null) {
      expect(c.counts, `chart "${c.name}" holds counts`).toBe(0);
      expect(c.brain, `chart "${c.name}" holds brain values`).toBe(0);
      continue;
    }
    expect(c[own]).toBeGreaterThan(0);
    expect(c[own === "counts" ? "brain" : "counts"]).toBe(0);
  }
  return charts.map((c) => c.name).sort();
}

async function openTab(page: Page, name: string) {
  await page.getByRole("tab", { name }).click();
  await expect(page.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
}

test.describe("reel screen", () => {
  test("wall, wording, card, buttons and layout", async ({ page }, info) => {
    // The read reel now also draws the 3D brain (WebGL in software in tests): allow the time.
    test.slow();
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(URL);
    await page.waitForLoadState("networkidle");

    // The footer's short line; its (i) opens to the full LICENCE 12 A text (tests/shell.spec.ts
    // checks that text word for word on this page too).
    const footer = page.locator("footer[data-licence]");
    await expect(footer).toContainText(en.footer.llama);
    await expect(footer).toContainText("CC BY-NC 4.0");
    await expect(footer.getByRole("button", { name: en.footer.hint, exact: true })).toHaveCount(1);

    // The card, as strategist precomputed it, in the order HOOK HIGH FLAT. D31 (analysis only):
    // the two TRY lines stay in the data and are not drawn, so the card shows 3 lines, not 5.
    const shown = reel.card.lines.filter((l) => l.tag !== "TRY");
    expect(shown).toHaveLength(3);
    const lines = page.locator("[data-card-text]");
    await expect(lines).toHaveText(shown.map((l) => l.text));
    await expect(page.locator("li[data-tag]")).toHaveCount(3);
    expect(await page.locator("li[data-tag]").evaluateAll((els) => els.map((e) => e.getAttribute("data-tag")))).toEqual(
      shown.map((l) => l.tag),
    );
    await expect(page.locator('li[data-tag="TRY"]')).toHaveCount(0);
    // The counts strip is its own element above the card (D18), one counts item per list item.
    // The trailing "as of" date repeats the counts stamp in the Facts (i), so the strip omits it.
    await expect(page.locator(`[aria-label="${en.reel.strip.label}"] li > [data-layer="counts"]`)).toHaveText(
      reel.card.counts.text.split(` ${en.reel.sep} `).filter((i) => !i.startsWith("as of ")),
    );

    // Separate charts: counts only in the counts chart, brain only in the timeline and the 3D
    // brain (D20); the tabs are Card / Beats / Areas / Facts and the page opens on Card (D18).
    expect(await chartOwners(page)).toEqual(["brain", "counts", "timeline"]);
    await expect(page.getByRole("tab")).toHaveText([en.reel.tabs.card, en.reel.tabs.beats, en.reel.tabs.areas, en.reel.tabs.facts]);
    await expect(page.getByRole("tab", { name: en.reel.tabs.card })).toHaveAttribute("aria-selected", "true");

    // Disabled kinds show their stage. D31: no Recreate button (coach.new_draft) on the reel page.
    await expect(page.locator('[data-job-kind="coach.new_draft"]')).toHaveCount(0);
    for (const kind of ["tribe.lanes"]) {
      const spec = jobKinds.kinds.find((k) => k.kind === kind)!;
      expect(spec.enabled).toBe(false);
      const button = page.locator(`[data-job-kind="${kind}"]`);
      await expect(button.getByRole("button")).toBeDisabled();
      await expect(button).toContainText(en.jobs.stage.replace("{stage}", String(spec.stage)));
    }
    // The private details: one lock button whose popover holds the note and the one laptop command (D31: no recreate row).
    const lock = page.locator("[data-private-row]").getByRole("button", { name: en.reel.private.title, exact: true });
    await expect(lock).toHaveCount(1);
    await lock.click();
    const details = page.locator("[data-private-details]");
    await expect(details).toContainText(en.reel.private.title);
    await expect(details).toContainText(en.reel.private.body);
    await expect(details.locator("code")).toHaveText([reel.local_cmd]);
    await page.keyboard.press("Escape");
    await expect(details).toHaveCount(0);

    // A time chip on the card moves the playhead; the arrow keys move it one second.
    const high = reel.card.lines.find((l) => l.tag === "HIGH")!;
    await page.locator('li[data-tag="HIGH"]').getByRole("button", { name: high.time! }).click();
    const slider = page.getByRole("slider", { name: en.reel.timeline.label });
    await expect(slider).toHaveAttribute("aria-valuenow", String(high.t));
    await expect(page.locator(`[data-playhead="${high.t}"]`)).toHaveCount(1);
    if (info.project.name === "phone") await expect(slider).toBeInViewport();
    await slider.focus();
    await page.keyboard.press("ArrowRight");
    await expect(slider).toHaveAttribute("aria-valuenow", String(high.t! + 1));

    expect(await wallBreaks(page)).toEqual([]);
    await checkText(page);
    await noSidewaysScroll(page);

    // Discount takes a reason and, in fixtures mode, says nothing was queued.
    await page.getByRole("button", { name: en.reel.discount.open }).click();
    await page.getByLabel(en.reel.discount.reason).fill("made-up reason for the test");
    await page.getByRole("button", { name: en.reel.discount.send }).click();
    await expect(page.getByRole("status").filter({ hasText: en.jobs.fixturesMode })).toBeVisible();
    await page.keyboard.press("Escape");

    await openTab(page, en.reel.tabs.beats);
    await expect(page.locator('[data-job-kind="coach.tag_shapes"]')).toContainText(en.jobs.stage.replace("{stage}", "2"));
    await expect(page.locator('[data-job-kind="coach.tag_shapes"]').getByRole("button")).toBeDisabled();
    for (const b of reel.beats) {
      const chip = page.locator(`[data-layer="shape"][data-status="${b.suggested ? "suggested" : "accepted"}"]`, { hasText: b.name });
      await expect(chip.first()).toBeVisible();
    }
    await page.getByRole("button", { name: en.reel.labels.acceptAll }).click();
    await expect(page.getByRole("status").filter({ hasText: en.jobs.fixturesMode }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: en.jobKinds.patterns_build })).toBeEnabled();
    expect(await wallBreaks(page)).toEqual([]);
    await checkText(page);
    await noSidewaysScroll(page);

    await openTab(page, en.reel.tabs.areas);
    expect(await chartOwners(page)).toEqual(["areas", "brain", "timeline"]);
    await expect(page.locator('[data-chart="areas"] [data-area-id^="net-"]')).toHaveCount(7);
    expect(await wallBreaks(page)).toEqual([]);
    await checkText(page);
    await noSidewaysScroll(page);

    await openTab(page, en.reel.tabs.facts);
    await expect(page.locator('dd[data-layer="facts"]')).toHaveText(reel.facts.map((f) => f.value));
    expect(await wallBreaks(page)).toEqual([]);
    await checkText(page);
    await noSidewaysScroll(page);

    expect(errors).toEqual([]);
  });

  test("edge mark, paid estimate, HOOK chip after its text", async ({ page }) => {
    await page.goto(URL);
    await page.waitForLoadState("networkidle");

    // Every edge moment carries its lower-confidence mark, at every width (D18).
    const edges = tribe.flat_stretches.filter((f) => f.edge).length + tribe.peaks.filter((p) => p.edge).length;
    expect(edges).toBeGreaterThan(0);
    const marks = page.locator("#reel-timeline [data-edge]");
    await expect(marks).toHaveCount(edges);
    for (const m of await marks.all()) {
      await expect(m).toBeVisible();
      await expect(m).toHaveText(en.reel.timeline.edge);
    }

    // A paid button shows its estimate even while its stage is off (D26).
    const lanes = jobKinds.kinds.find((k) => k.kind === "tribe.lanes")!;
    await expect(page.locator('[data-job-kind="tribe.lanes"] [data-estimate]')).toHaveText(
      en.jobs.estimate.replace("{usd}", lanes.estimate_usd.toFixed(2)),
    );

    // HOOK ends "first word at": its chip follows the text; the other chips lead their line.
    const order = await page.locator("li[data-tag]").evaluateAll((rows) =>
      rows.map((r) => {
        const kids = [...r.querySelectorAll("[data-card-text], button")];
        return [r.getAttribute("data-tag"), kids.map((k) => (k.hasAttribute("data-card-text") ? "text" : "chip")).join(",")];
      }),
    );
    expect(order).toContainEqual(["HOOK", "text,chip"]);
    expect(order).toContainEqual(["HIGH", "chip,text"]);
  });

  test("every board row has a page; one without a TRIBE read", async ({ page }) => {
    for (const r of board.reels) {
      await page.goto(`/reels/${r.sc}`);
      await expect(page.locator("li[data-tag]")).toHaveCount(3);
      await expect(page.getByText(en.errors.notFound)).toHaveCount(0);
    }
    await page.goto(`/reels/${factsReel.shortcode}`);
    await page.waitForLoadState("networkidle");
    expect(await page.locator("li[data-tag]").evaluateAll((els) => els.map((e) => e.getAttribute("data-tag")))).toEqual(
      factsReel.card.lines.filter((l) => l.tag !== "TRY").map((l) => l.tag),
    );
    await expect(page.locator("[data-card-text]")).toHaveText(factsReel.card.lines.filter((l) => l.tag !== "TRY").map((l) => l.text));
    await expect(page.getByText(en.reel.timeline.empty.pill)).toBeVisible();
    // The opt-in note waits behind the (i) by the deep read button (D30), word for word.
    const lanes = jobKinds.kinds.find((k) => k.kind === "tribe.lanes")!;
    const optIn = en.reel.timeline.empty.body
      .replace("{usd}", lanes.estimate_usd.toFixed(2))
      .replace("{n}", String(jobKinds.limits.tribe_reads_per_month));
    expect(await page.locator("main").innerText()).not.toContain(optIn);
    await page.locator("[data-empty-action]").getByRole("button", { name: en.reel.timeline.empty.hintLabel, exact: true }).click();
    await expect(page.locator("[data-hint]")).toHaveText(optIn);
    await expect(page.locator("[data-hint]")).toHaveAttribute("data-layer", "ui");
    await page.keyboard.press("Escape");
    await expect(page.locator("[data-hint]")).toHaveCount(0);
    await expect(page.locator('main [data-layer="brain"]')).toHaveCount(0);
    // No read: no 3D brain, no Areas tab, no brain downloads.
    await expect(page.locator('[data-chart="brain"], [data-chart="areas"], [data-download-menu]')).toHaveCount(0);
    await expect(page.getByRole("tab", { name: en.reel.tabs.areas })).toHaveCount(0);
    expect(await page.locator("[data-chart]").evaluateAll((els) => els.map((e) => e.getAttribute("data-chart")).sort())).toEqual([
      "counts",
      "timeline",
    ]);
    expect(await wallBreaks(page)).toEqual([]);
    await checkText(page);
    await noSidewaysScroll(page);
  });

  test("hints and swatches: found by name, exact text, own layer, 44px on touch; teal 'this reel' dot", async ({ page }, info) => {
    test.slow();
    const phone = info.project.name === "phone";
    const T = en.reel.timeline;
    const B = en.reel.brain;
    /** Opens a trigger as a reader does: a tap on a phone (after checking its 44px hit area), a
     *  hover on a laptop. */
    async function open(trigger: Locator) {
      await expect(trigger).toHaveCount(1);
      if (phone) {
        const box = await trigger.evaluate((el) => {
          const s = getComputedStyle(el, "::before");
          return [parseFloat(s.width), parseFloat(s.height)];
        });
        expect(box[0]).toBeGreaterThanOrEqual(44);
        expect(box[1]).toBeGreaterThanOrEqual(44);
        await trigger.tap();
      } else {
        await trigger.hover();
      }
    }
    async function close(popover: Locator) {
      await page.keyboard.press("Escape");
      await page.mouse.move(0, 0);
      await expect(popover).toHaveCount(0);
    }

    // Each explanation, caveat and credit moved behind an (i) (D30), word for word: the trigger
    // by its name (inside `scope`), the hint's exact text (or its parts' texts), and its layer.
    type Hint = { tab: keyof typeof en.reel.tabs; scope?: string; label: string; text: string[]; part?: string; layer: "ui" | "brain" };
    const credits = [B.credit.atlas, B.credit.hcp];
    const hints: Hint[] = [
      { tab: "card", label: en.reel.counts.footnoteLabel, part: "[data-counts-note]", text: [en.reel.counts.footnote], layer: "ui" },
      { tab: "card", label: en.reel.card.footnoteLabel, text: [reel.card.footnote!], layer: "brain" },
      {
        tab: "card",
        scope: "#reel-timeline",
        label: T.notes,
        part: "[data-read-notes] > span",
        text: [tribe.scale.label, reel.stamps.brain!, ...tribe.warnings.map((w) => w.text)],
        layer: "brain",
      },
      {
        tab: "card",
        scope: '[data-chart="brain"]',
        label: en.ui.hintAbout.replace("{topic}", B.legend.label),
        part: "[data-brain-key-hint] > span",
        text: [B.legend.scale, B.legend.about],
        layer: "brain",
      },
      { tab: "card", scope: "#reel-timeline [data-brain-credits]", label: B.creditsLabel, part: "[data-credits-text] > span", text: credits, layer: "ui" },
      { tab: "beats", label: en.reel.labels.hintLabel, text: [en.reel.labels.hint], layer: "ui" },
      { tab: "beats", label: en.reel.beats.groupHintLabel, text: [en.reel.beats.groupHint], layer: "ui" },
      { tab: "beats", label: en.reel.labels.rebuildLabel, text: [en.reel.labels.rebuild], layer: "ui" },
      { tab: "areas", scope: '[data-chart="areas"] [data-brain-credits]', label: B.creditsLabel, part: "[data-credits-text] > span", text: credits, layer: "ui" },
    ];
    await page.goto(URL);
    await page.waitForLoadState("networkidle");
    const hint = page.locator("[data-hint]");
    for (const h of hints) {
      await openTab(page, en.reel.tabs[h.tab]);
      await open((h.scope ? page.locator(h.scope) : page).getByRole("button", { name: h.label, exact: true }));
      await expect(h.part ? hint.locator(h.part) : hint).toHaveText(h.text);
      await expect(hint).toHaveAttribute("data-layer", h.layer);
      await close(hint);
      // The old inline text is gone from the page.
      const main = await page.locator("main").innerText();
      for (const text of h.text) expect(main).not.toContain(text);
    }

    // The board's flags in full wait in the counts (i) (the strip shows them short): counts only.
    const boardRow = board.reels.find((r) => r.sc === reel.shortcode)!;
    expect(boardRow.badges.length).toBeGreaterThan(0);
    await openTab(page, en.reel.tabs.card);
    await open(page.getByRole("button", { name: en.reel.counts.footnoteLabel, exact: true }));
    await expect(hint.locator('[data-flags] li > [data-layer="counts"]')).toHaveText(boardRow.badges.map((b) => b.label));
    await expect(hint.locator('[data-layer="brain"]')).toHaveCount(0);
    await close(hint);

    // Facts: values only; one (i) opens to where they come from, "About this data" (one stamp
    // per layer, one row each, never two layers in a row) and the wall sentence word for word.
    await openTab(page, en.reel.tabs.facts);
    await open(page.getByRole("button", { name: en.reel.facts.about, exact: true }));
    await expect(hint).toHaveAttribute("data-layer", "ui");
    await expect(hint.locator("[data-facts-source]")).toHaveText(en.reel.facts.hint);
    await expect(hint.locator("[data-wall]")).toHaveText(en.reel.facts.wall);
    const stamps = hint.locator('[data-stamps] > li > [data-layer]:not([data-layer="ui"])');
    await expect(stamps).toHaveText([reel.stamps.counts, reel.stamps.shape, reel.stamps.brain]);
    expect(await stamps.evaluateAll((els) => els.map((e) => e.getAttribute("data-layer")))).toEqual(["counts", "shape", "brain"]);
    await expect(hint.locator("[data-stamps] > li").last()).toHaveText(reel.stamps.page);
    const mixed = await hint.locator("[data-stamps] > li").evaluateAll(
      (rows) => rows.filter((r) => new Set([...r.querySelectorAll("[data-layer]")].map((e) => e.getAttribute("data-layer")).filter((l) => l !== "ui")).size > 1).length,
    );
    expect(mixed).toBe(0);
    await close(hint);
    const factsMain = await page.locator("main").innerText();
    for (const text of [en.reel.facts.hint, en.reel.facts.wall, reel.stamps.counts, reel.stamps.shape, reel.stamps.page]) {
      expect(factsMain).not.toContain(text);
    }

    // Legends are swatches only: each name shows on hover or tap and names the swatch.
    await openTab(page, en.reel.tabs.card);
    const swatches: Array<[string, string, string]> = [
      ['[data-chart="counts"]', "own", en.reel.counts.own.replace("{n}", String(boardRow.peer!.ticks.length))],
      ["#reel-timeline", "line", T.legend.line],
      ["#reel-timeline", "playhead", T.legend.playhead],
      ['[data-chart="brain"]', "near", B.legend.near],
    ];
    for (const [scope, key, name] of swatches) {
      const trigger = page.locator(`${scope} [data-swatch="${key}"]`);
      await expect(trigger).toHaveAccessibleName(name);
      await open(trigger);
      const tip = page.locator(`[data-swatch-name="${key}"]`);
      await expect(tip).toHaveText(name);
      await close(tip);
    }
    const cardMain = await page.locator("main").innerText();
    for (const name of [T.legend.line, T.legend.fill, T.legend.suggested, T.legend.accepted, T.legend.playhead, swatches[0][2]]) {
      expect(cardMain).not.toContain(name);
    }

    // The "this reel" dot in the counts chart is the counts teal token.
    await openTab(page, en.reel.tabs.card);
    const [me, teal] = await page.evaluate(() => {
      const probe = document.createElement("span");
      probe.style.backgroundColor = "var(--counts)";
      document.body.append(probe);
      const want = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return [getComputedStyle(document.querySelector("[data-chart=counts] [data-me]")!).backgroundColor, want];
    });
    expect(me).toBe(teal);
  });

  test("with its video: the video chart owns neither layer; wall and wording hold", async ({ page }) => {
    // The fixtures test hook (lib/data.ts VIDEO_TEST_COOKIE) shows the player; the synthetic clip
    // stands in for the video route (tests/video.spec.ts checks the player itself).
    const clip = path.resolve(__dirname, "assets", "testclip.mp4");
    await page.context().addCookies([{ name: "tribe-test-video", value: "1", url: test.info().project.use.baseURL! }]);
    await page.route(/\/reels\/[^/]+\/video(\?.*)?$/, (route) =>
      route.fulfill(existsSync(clip) ? { path: clip, contentType: "video/mp4" } : { status: 404 }),
    );
    await page.goto(URL);
    await page.waitForLoadState("networkidle");
    expect(await chartOwners(page)).toEqual(["brain", "counts", "timeline", "video"]);
    expect(await wallBreaks(page)).toEqual([]);
    await checkText(page);
    await noSidewaysScroll(page);
    await openTab(page, en.reel.tabs.areas);
    expect(await chartOwners(page)).toEqual(["areas", "brain", "timeline", "video"]);
    expect(await wallBreaks(page)).toEqual([]);
  });

  test("screenshots, light and dark", async ({ page }, info) => {
    await page.goto(URL);
    await page.waitForLoadState("networkidle");
    await page.locator('li[data-tag="HIGH"] button').click();
    await page.mouse.move(0, 0);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(SHOTS, `reel-${info.project.name}-light.png`), fullPage: true });
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await page.screenshot({ path: path.join(SHOTS, `reel-${info.project.name}-dark.png`), fullPage: true });
  });
});
