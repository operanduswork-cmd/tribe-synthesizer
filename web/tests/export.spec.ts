// The Export page (/export, Round 6) in fixtures mode, at phone (390x844) and laptop (1280x800):
// the page is one button (44px on a phone) behind a plain link, the download is one valid JSON
// file with four separate top-level keys (counts and brain output never share an object, D20),
// framing "predicted average-brain response", no words, transcripts, captions, stills or video
// fields (D30), one brain object per read reel and nothing across reels (D21), and /import lands
// on /export.

import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import en from "../copy/en.json";

const PROJECT = path.resolve(__dirname, "..", "..");
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

/** Every object key in a JSON value, at any depth. */
function keysOf(v: unknown, out = new Set<string>()): Set<string> {
  if (Array.isArray(v)) v.forEach((x) => keysOf(x, out));
  else if (v && typeof v === "object")
    for (const [k, x] of Object.entries(v)) {
      out.add(k);
      keysOf(x, out);
    }
  return out;
}

test("export: layout, footer, one button, no scroll", async ({ page }, info) => {
  const errors = watchConsole(page);
  await page.goto("/export");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(en.pages.export.title);

  const footer = page.locator("footer[data-licence]");
  await expect(footer).toContainText(en.footer.llama);
  await expect(footer).toContainText("CC BY-NC 4.0");

  const button = page.getByRole("link", { name: en.export.button, exact: true });
  await expect(button).toBeVisible();
  await expect(button).toHaveAttribute("href", "/export/data");
  await expect(button).toHaveAttribute("download", "");
  const b = await button.boundingBox();
  if (info.project.name === "phone") expect(b!.height, "44px tap target").toBeGreaterThanOrEqual(43.5);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "no horizontal scroll").toBeLessThanOrEqual(0);

  // No counts value and no brain value on the page itself (D20 wall).
  expect(await page.locator('main [data-layer="counts"], main [data-layer="brain"]').count()).toBe(0);
  const text = await page.locator("body").innerText();
  expect(bannedIn(text), "banned words in the page text").toEqual([]);
  expect(text.includes(String.fromCharCode(0x2014)), "no em dash in the page text").toBe(false);

  // The one explanation sits behind an (i), by touch or click.
  const trigger = page.getByRole("button", { name: en.export.hintLabel });
  if (info.project.name === "phone") await trigger.tap();
  else await trigger.click();
  await expect(page.locator("[data-hint]")).toHaveText(en.export.hint);
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-hint]")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("export: the download is one JSON file with separate top-level keys", async ({ page, request }) => {
  const res = await request.get("/export/data");
  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"]).toContain("application/json");
  expect(res.headers()["cache-control"]).toBe("private, no-store");
  expect(res.headers()["content-disposition"]).toBe('attachment; filename="tribe-export.json"');

  const body = await res.json();
  expect(Object.keys(body)).toEqual(["meta", "reels", "patterns", "brain"]);
  expect(body.meta.framing).toBe("predicted average-brain response");
  expect(body.meta.licence).toContain("CC BY-NC 4.0");
  expect(body.meta.licence).toContain("Meta FAIR");
  expect(body.meta.built_with).toBe(en.footer.llama);

  // Counts and shape layer only; the board has rows and each is one flat record.
  expect(body.reels.length).toBeGreaterThan(0);
  for (const r of body.reels) {
    expect(Object.keys(r)).toEqual(["shortcode", "handle", "duration_s", "plays", "posted", "x_own_median", "shape"]);
    expect(Object.keys(r.shape)).toEqual(["hook", "format", "cta", "beats"]);
  }
  expect(body.patterns).not.toBeNull();

  // Brain: one object per reel with a read, never counts, never an aggregate across reels (D21).
  expect(body.brain.length).toBeGreaterThan(0);
  const seen = new Set<string>();
  for (const b of body.brain) {
    expect(Object.keys(b)).toEqual(["shortcode", "job_id", "framing", "time_s", "atlas", "areas"]);
    expect(b.framing).toBe("predicted average-brain response");
    expect(seen.has(b.shortcode), "one object per reel").toBe(false);
    seen.add(b.shortcode);
    expect(b.areas.hcp_left.length).toBe(b.atlas.hcp_labels.length);
    expect(b.areas.hcp_left[0].length).toBe(b.time_s.length);
    expect(body.reels.some((r: { shortcode: string }) => r.shortcode === b.shortcode)).toBe(true);
  }

  // The fields of the other layers never cross over (D20), and no words, transcripts, captions,
  // stills or video (D30).
  const brainKeys = keysOf(body.brain);
  for (const k of ["plays", "x_own_median", "counts", "x", "median"]) expect(brainKeys.has(k), `brain key ${k}`).toBe(false);
  const countsKeys = keysOf(body.reels);
  for (const k of ["areas", "hcp_left", "time_s", "tribe"]) expect(countsKeys.has(k), `reels key ${k}`).toBe(false);
  const all = keysOf(body);
  for (const k of ["words", "transcript", "transcripts", "caption", "captions", "still", "stills", "video", "video_url", "pathname", "image", "images"])
    expect(all.has(k), `banned field ${k}`).toBe(false);
  expect(JSON.stringify(body)).not.toMatch(/\.(mp4|mov|webm|jpe?g|png)\b/i);
  void page;
});

test("export: /import redirects to /export", async ({ page }) => {
  await page.goto("/import");
  await expect(page).toHaveURL(/\/export$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(en.pages.export.title);
});

test("export: the preview shows exactly the downloaded JSON, copy works, no page scroll", async ({ page, request, context }, info) => {
  test.setTimeout(90_000);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => undefined);
  const res = await request.get("/export/data");
  const downloaded = await res.text();
  await page.goto("/export");
  await page.waitForLoadState("networkidle");

  const pre = page.locator("[data-export-json]");
  // Closed until the Preview JSON button is clicked (his call, 16 Oct).
  await expect(pre).toHaveCount(0);
  const openBtn = page.locator("[data-export-open]");
  await expect(openBtn).toHaveText(en.export.showPreview);
  await expect(async () => {
    await openBtn.click();
    await expect(pre).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 40_000 });
  await expect(openBtn).toHaveText(en.export.hidePreview);
  const toggle = page.locator("[data-export-toggle]");
  if (await toggle.count()) {
    await toggle.click();
    await expect(pre.locator("> span").last()).toBeAttached();
  }
  const shown = await pre.evaluate((el) => Array.from(el.children).map((c) => c.textContent ?? "").join("\n"));
  expect(JSON.parse(shown)).toEqual(JSON.parse(downloaded));
  expect(shown.split("\n")[1].startsWith("  \""), "2-space indent").toBe(true);

  // One stats line: size, reels and brain reads.
  const body = JSON.parse(downloaded) as { reels: unknown[]; brain: unknown[] };
  await expect(page.locator("[data-export-stats]")).toContainText(`${body.reels.length} reels, ${body.brain.length} brain reads`);

  // The panel scrolls inside itself; the page never scrolls sideways.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "no horizontal page scroll").toBeLessThanOrEqual(0);

  const copyBtn = page.locator("[data-export-copy]");
  const b = await copyBtn.boundingBox();
  expect(b!.height, "44px tap target").toBeGreaterThanOrEqual(43.5);
  await expect(copyBtn).toHaveAccessibleName(en.export.copy);
  // Retry the click: the first one can land before the page has hydrated.
  await expect(async () => {
    await copyBtn.click();
    await expect(copyBtn).toHaveText(en.export.copied, { timeout: 2000 });
  }).toPass({ timeout: 40_000 });
  if (info.project.name !== "phone") {
    const clip = await page.evaluate(() => navigator.clipboard.readText()).catch(() => null);
    if (clip !== null) expect(JSON.parse(clip)).toEqual(JSON.parse(downloaded));
  }

  // Still no banned fields in what is on screen.
  const keys = keysOf(JSON.parse(shown));
  for (const k of ["words", "transcript", "caption", "captions", "still", "stills", "video", "video_url"]) expect(keys.has(k)).toBe(false);
});
