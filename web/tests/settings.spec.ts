// Settings -> Jobs in fixtures mode, at phone (390x844) and laptop (1280x800) widths: no console
// errors, no sideways scroll, the licence footer, the D20 wall per row, banned words (read from
// strategist's own rules through Python, so this file names none of them). Jobs: every status is a
// dot and a word with no red or green fills, spend against its caps, the runner, the Pause switch,
// and the round 3 explanations behind (i) word for word. Moved here from lab.spec.ts in round 4
// (D31: the Script lab is gone), unchanged in what they assert.

import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import en from "../copy/en.json";
import jobRows from "../fixtures/rows/jobs.json";

const JOBS = "/settings/jobs";
const PROJECT = path.resolve(__dirname, "..", "..");

// strategist's banned-word and rating check (dashboard/render.py find_banned), run on the text.
const FIND_BANNED =
  "import json, sys\nfrom strategist import store\nprint(json.dumps(store.rules().find_banned(sys.stdin.read())))";

function bannedIn(text: string): string[] {
  const out = execFileSync("python", ["-c", FIND_BANNED], {
    cwd: PROJECT,
    input: text,
    encoding: "utf-8",
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  return JSON.parse(out) as string[];
}

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function open(page: Page, url: string) {
  await page.goto(url);
  await page.waitForLoadState("networkidle");
}

/** Shared checks for any page: footer, no sideways scroll, the wall per row, banned words. */
async function commonChecks(page: Page) {
  const footer = page.locator("footer[data-licence]");
  await expect(footer).toContainText(en.footer.llama);
  await expect(footer).toContainText("CC BY-NC 4.0");

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "no horizontal scroll").toBeLessThanOrEqual(0);

  // D20: a counts value and a brain value never sit in the same row or line container.
  expect(await wallBreaks(page)).toEqual([]);

  const text = await page.locator("body").innerText();
  expect(bannedIn(text), "banned words in the page text").toEqual([]);
  expect(text.includes(String.fromCharCode(0x2014)), "no em dash in the page text").toBe(false);
  expect(/(?<![A-Za-z])LOW(?![A-Za-z])/.test(text), "say FLAT, not LOW").toBe(false);

  // Every value carries a layer: nothing with text sits outside a data-layer element in main.
  const unlayered = await page.evaluate(() => {
    const out: string[] = [];
    const walker = document.createTreeWalker(document.querySelector("main") ?? document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const t = (n.textContent ?? "").trim();
      const el = n.parentElement;
      if (!t || !el || el.closest("[data-layer]") || el.closest(".sr-only, [aria-hidden='true']")) continue;
      if (el.closest("button, label, h1, h2, h3, dt, summary, [role='tab'], [role='status']")) continue;
      out.push(t.slice(0, 40));
    }
    return out;
  });
  expect(unlayered, "text outside any data-layer").toEqual([]);
}

/** D20: rows or line containers anywhere on the page (open hints included) where a counts value
 *  and a brain value sit together. */
async function wallBreaks(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const ROW = '[data-row], tr, li, p, dd, [role="row"]';
    const bad: string[] = [];
    const pairs: Array<[string, string]> = [
      ["counts", "brain"],
      ["brain", "counts"],
    ];
    for (const [a, b] of pairs) {
      for (const el of Array.from(document.querySelectorAll(`[data-layer="${a}"]`))) {
        const row = el.closest(ROW) ?? el.parentElement;
        if (row && (row.querySelector(`[data-layer="${b}"]`) || row.closest(`[data-layer="${b}"]`))) {
          bad.push(`${a} next to ${b}: ${(row.textContent ?? "").slice(0, 80)}`);
        }
      }
    }
    return bad;
  });
}

/** Opens an (i) hint by touch on a phone (checking its 44px hit area) or by click on a laptop,
 *  and returns the open hint (the patterns spec's helper). */
async function openHint(page: Page, trigger: Locator, phone: boolean): Promise<Locator> {
  await expect(trigger).toHaveCount(1);
  if (phone) {
    // A 16px icon with a 44px hit area on touch.
    const hit = await trigger.evaluate((el) => {
      const s = getComputedStyle(el, "::before");
      return Math.min(parseFloat(s.width), parseFloat(s.height));
    });
    expect(hit, "44px hit area on touch").toBeGreaterThanOrEqual(44);
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

/** Elements in main with a red or green background fill (status is told by dot shape and word,
 *  never by a red or green fill). */
async function redGreenFills(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll("main *"))) {
      const m = /rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/.exec(getComputedStyle(el).backgroundColor);
      if (!m || (m[4] !== undefined && Number(m[4]) < 0.05)) continue;
      const [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])];
      if ((r - Math.max(g, b) > 60) || (g - Math.max(r, b) > 60)) out.push(`${el.tagName} ${r},${g},${b}`);
    }
    return out;
  });
}

// ---------------------------------------------------------------- Settings → Jobs

test("jobs: queue, spend, runner, pause", async ({ page }) => {
  const errors = watchConsole(page);
  await open(page, JOBS);
  await commonChecks(page);

  // On a phone the queue comes before the runner and spend cards.
  if (page.viewportSize()!.width < 640) {
    const queueY = (await page.locator("[data-queue]").boundingBox())!.y;
    expect(queueY).toBeLessThan((await page.locator('[data-spend="modal"]').boundingBox())!.y);
  }

  // Every job shows its status as a dot and a word.
  const rows = page.locator("[data-job]");
  await expect(rows).toHaveCount(jobRows.jobs.length);
  for (const j of jobRows.jobs) {
    const row = page.locator(`[data-job="${j.id}"]`);
    await expect(row.locator("summary [data-tone]")).toBeVisible();
    await expect(row.locator("summary")).toContainText(en.status[j.status as keyof typeof en.status]);
  }

  // No red or green fills anywhere on the page (status is told by dot shape and word).
  expect(await redGreenFills(page)).toEqual([]);

  // A row opens to its fixed progress lines.
  const done = page.locator('[data-status="done"]').first();
  await done.locator("summary").click();
  await expect(done).toContainText("Started.");

  // Spend against the caps, and the runner.
  await expect(page.locator('[data-spend="modal"]')).toContainText("$0.42");
  await expect(page.locator('[data-spend="modal"]')).toContainText("of $30.00 cap");
  await expect(page.locator('[data-spend="apify"]')).toContainText(en.settings.spend.notRead);
  await expect(page.locator("[data-runner]")).toContainText(en.runner.fixtures);
  await expect(page.locator("main")).toContainText(en.settings.runner.stepStartCommand);

  // Pause: fixtures mode changes nothing and says so.
  const sw = page.getByRole("switch");
  await expect(sw).toHaveAttribute("aria-checked", "false");
  await sw.click();
  await expect(page.locator("[data-pause] [role='status']")).toHaveText(en.jobs.fixturesMode);
  await expect(sw).toHaveAttribute("aria-checked", "false");
  expect(errors).toEqual([]);
});

// Round 3 text cut (D30): the settings explanations moved behind (i), word for word.
test("jobs: round 3 text cut, explanations behind (i) word for word", async ({ page }, info) => {
  const phone = info.project.name === "phone";
  await open(page, JOBS);
  const main = page.locator("main");
  // No subtitle, no stamps, no long bodies on the page itself.
  await expect(main.locator("header").first().locator("p:not([role=status])")).toHaveCount(0);
  for (const gone of [
    en.settings.runner.setupBody,
    en.settings.runner.stepStartBody,
    en.settings.runner.stepOnceCommand,
    en.settings.spend.modalSource,
    en.settings.spend.apifySource,
    "as of",
    "free credit",
    en.settings.limits.body,
  ]) {
    expect(await main.innerText(), gone).not.toContain(gone);
  }
  // Values stay: spend against the same cap wording for both services.
  await expect(page.locator('[data-spend="modal"]')).toContainText(en.settings.spend.ofCap.replace("{cap}", "30.00"));
  await expect(page.locator('[data-spend="apify"]')).toContainText(en.settings.spend.ofCap.replace("{cap}", "4.50"));
  await expect(page.locator("[data-runner-steps] code")).toHaveText(en.settings.runner.stepStartCommand);

  // Modal: where the number comes from and when it was read.
  let hint = await openHint(page, page.getByRole("button", { name: en.settings.spend.sourceLabel.replace("{service}", en.settings.spend.modal) }), phone);
  await expect(hint).toContainText(en.settings.spend.modalSource);
  await expect(hint.locator("[data-as-of]")).toContainText(/^Updated .+\.$/);
  await closeHint(page);
  // Apify: its source, the free-credit stop, when it was read.
  hint = await openHint(page, page.getByRole("button", { name: en.settings.spend.sourceLabel.replace("{service}", en.settings.spend.apify) }), phone);
  await expect(hint).toContainText(en.settings.spend.apifySource);
  await expect(hint).toContainText(en.settings.spend.apifyCap.replace("{cap}", "4.50"));
  await closeHint(page);
  // Starting the runner: why, and the two other ways, each with its command.
  hint = await openHint(page, page.getByRole("button", { name: en.settings.runner.setupLabel }), phone);
  for (const t of [
    en.settings.runner.setupBody,
    en.settings.runner.stepStartBody,
    en.settings.runner.stepOnce,
    en.settings.runner.stepOnceBody,
    en.settings.runner.stepLogon,
    en.settings.runner.stepLogonBody,
  ]) await expect(hint).toContainText(t);
  await expect(hint.locator("code")).toHaveText([en.settings.runner.stepOnceCommand, en.settings.runner.stepLogonCommand]);
  await closeHint(page);
  // Limits and pausing open to exactly their sentence.
  hint = await openHint(page, page.getByRole("button", { name: en.settings.limits.hintLabel }), phone);
  await expect(hint).toHaveText(en.settings.limits.body);
  await closeHint(page);
  hint = await openHint(page, page.getByRole("button", { name: en.settings.pause.hintLabel }), phone);
  await expect(hint).toHaveText(en.settings.pause.body);
  await closeHint(page);
  // The Radix form checkbox beside the switch is never laid out.
  expect(await page.locator("[data-pause] input").evaluateAll((els) => els.filter((e) => e.getBoundingClientRect().height > 0).length)).toBe(0);
});
