// The 3D brain, the Areas tab and the brain downloads (D28) in fixtures mode, at phone (390x844)
// and laptop (1280x800) widths. WebGL runs on SwiftShader (playwright.config.ts). Checks:
// - the canvas draws (more than 20 colours), the pixels change with the second, and the scale
//   (data-scale-abs) never changes;
// - the timeline, the brain scrubber and the canvas share one second, and Play steps them all;
// - hover links both ways (Areas rows <-> the brain, lane names -> the brain), a tap on touch;
// - no ranking: rows in atlas order at three seconds, the "coloured on the brain" marks match the
//   fixture, no rank, ordinal or rating text (dashboard/render.py find_banned);
// - the numbers files: exact header, no count words, banned words none, the row count, and the
//   menu items really download;
// - the wall: no counts value inside the timeline, the brain or the Areas tab (D20);
// - reduced motion: nothing animates and Play never blends;
// - no WebGL: the fallback, no console errors, no sideways scroll; a lost context reloads;
// - phone: a sideways drag turns the brain, a vertical swipe scrolls the page, 44px controls.
// Plus Node-only checks of the colour scale (symmetric, one scale) and the frames decoder.

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { DEFAULT_PALETTE, LUT_SIZE, alphaAt, buildLut, colorFor, lutU, poleColor, rgbToOklch } from "../components/reel/brain/lut";
import en from "../copy/en.json";
import brain from "../fixtures/brain.json";
import reel from "../fixtures/reel.json";
import tribe from "../fixtures/tribe.json";
import { BRAIN, BrainFormatError, decodeFrames, frameRow } from "../lib/brain/format";

const SC = reel.shortcode;
const URL = `/reels/${SC}`;
const ROOT = path.resolve(__dirname, "..", "..");
const T = brain.time_s.length;
const VMAX = brain.scale.vmax;
const AREAS_HEADER = "second,clock,level,area,hemisphere,network,feeds_line,value";
const COUNT_TERMS_RE = /(?<![A-Za-z0-9])(?:plays|likes|comments|medians?|outliers?|followers)(?![A-Za-z0-9])|(?<![\w.])\d+(?:\.\d+)?[x×](?![A-Za-z0-9])/i;
const FIND_BANNED =
  "import json, sys\nsys.path.insert(0, '.')\nfrom dashboard.render import find_banned\nprint(json.dumps(find_banned(sys.stdin.read())))";

/** Banned words and rating numbers in a text, by the same check the pages run (D20). */
function banned(text: string): string[] {
  const out = execFileSync("python", ["-c", FIND_BANNED], {
    cwd: ROOT,
    input: text,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  return JSON.parse(out) as string[];
}

/** Where a mean sits on the reel's one scale (components/reel/brain/view.ts onBrain). */
const onBrain = (v: number) => (Math.abs(v) / VMAX >= brain.scale.grey_below ? (v > 0 ? "above" : "below") : "none");

const timeline = (page: Page) => page.getByRole("slider", { name: en.reel.timeline.label });
const scrubber = (page: Page) => page.getByRole("slider", { name: en.reel.brain.second });
const canvas = (page: Page) => page.locator("[data-brain-canvas]");

async function brainReady(page: Page) {
  await page.locator('[data-chart="brain"]').scrollIntoViewIfNeeded();
  await expect(canvas(page)).toHaveAttribute("data-ready", "true", { timeout: 60_000 });
}

/** Two animation frames, so a draw the page asked for has happened. */
async function frames(page: Page) {
  await page.evaluate(() => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r()))));
}

/** Distinct colours (6 bits a channel) and a hash of the canvas pixels, read through toDataURL. */
async function pixels(c: Locator): Promise<{ colours: number; hash: number }> {
  return c.evaluate(async (el: HTMLCanvasElement) => {
    const img = new Image();
    img.src = el.toDataURL("image/png");
    await img.decode();
    const out = document.createElement("canvas");
    out.width = img.width;
    out.height = img.height;
    const ctx = out.getContext("2d")!;
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, out.width, out.height).data;
    const seen = new Set<number>();
    let hash = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] === 0) continue;
      seen.add(((d[i] >> 2) << 12) | ((d[i + 1] >> 2) << 6) | (d[i + 2] >> 2));
      hash = (Math.imul(hash, 31) + d[i] + 7 * d[i + 1] + 13 * d[i + 2]) | 0;
    }
    return { colours: seen.size, hash };
  });
}

async function noSidewaysScroll(page: Page) {
  const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(scroll).toBeLessThanOrEqual(width);
}

async function openAreas(page: Page) {
  await page.getByRole("tab", { name: en.reel.tabs.areas }).click();
  await expect(page.getByRole("tab", { name: en.reel.tabs.areas })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-chart="areas"]')).toBeVisible();
}

/** The Areas rows in the order they sit on the page, as their ids. */
const rowIds = (page: Page) => page.locator('[data-chart="areas"] [data-area-id]').evaluateAll((els) => els.map((e) => e.getAttribute("data-area-id")));

test.describe("3D brain", () => {
  // The first draw builds the synthetic assets on the server and runs WebGL in software.
  test.describe.configure({ timeout: 90_000 });

  test("draws, changes with the second, keeps one scale", async ({ page }) => {
    await page.goto(URL);
    await brainReady(page);
    const c = canvas(page);
    const scale = await c.getAttribute("data-scale-abs");
    expect(Number(scale)).toBe(VMAX);
    const first = await c.getAttribute("data-frame");
    const before = await pixels(c);
    expect(before.colours).toBeGreaterThan(20);

    await timeline(page).focus();
    for (const key of ["PageUp", "PageUp", "ArrowRight", "ArrowRight", "ArrowRight"]) await page.keyboard.press(key);
    await expect(c).toHaveAttribute("data-frame", String(Number(first) + 13));
    await frames(page);
    const after = await pixels(c);
    expect(after.colours).toBeGreaterThan(20);
    expect(after.hash).not.toBe(before.hash);
    expect(await c.getAttribute("data-scale-abs")).toBe(scale);

    // Turning the brain changes the picture but never the scale.
    await page.locator("[data-angle-button=inside]").click();
    await expect(c).toHaveAttribute("data-angle", "inside");
    await page.locator("[data-brain-reset]").click();
    await expect(c).toHaveAttribute("data-angle", "outside");
    expect(await c.getAttribute("data-scale-abs")).toBe(scale);
  });

  test("timeline, scrubber and brain share one second", async ({ page }) => {
    await page.goto(URL);
    await brainReady(page);
    const t0 = Number(await timeline(page).getAttribute("aria-valuenow"));
    expect(t0).toBe(Math.min(...tribe.peaks.filter((p) => !p.edge).map((p) => p.t)));
    await expect(scrubber(page)).toHaveAttribute("aria-valuenow", String(t0));
    await expect(canvas(page)).toHaveAttribute("data-frame", String(t0));

    await timeline(page).focus();
    await page.keyboard.press("ArrowRight");
    await expect(scrubber(page)).toHaveAttribute("aria-valuenow", String(t0 + 1));
    await expect(canvas(page)).toHaveAttribute("data-frame", String(t0 + 1));
    await expect(page.locator(`[data-brain-playhead="${t0 + 1}"]`)).toHaveCount(1);
    await expect(page.locator("[data-playhead]")).toHaveCount(1);

    await scrubber(page).focus();
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowLeft");
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", String(t0 - 1));
    await expect(canvas(page)).toHaveAttribute("data-frame", String(t0 - 1));
  });

  test("Play steps the timeline and the brain together", async ({ page }) => {
    await page.clock.install();
    await page.goto(URL);
    await expect(scrubber(page)).toBeAttached();
    // Time moves only when the test says so (a busy main thread can never add a step).
    await page.clock.pauseAt(await page.evaluate(() => Date.now() + 500));
    const t0 = Number(await timeline(page).getAttribute("aria-valuenow"));
    await page.getByRole("button", { name: en.reel.brain.play }).click();
    await expect(page.getByRole("button", { name: en.reel.brain.pause })).toBeVisible();
    await page.clock.runFor(1000);
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", String(t0 + 1));
    await expect(scrubber(page)).toHaveAttribute("aria-valuenow", String(t0 + 1));
    await page.clock.runFor(1000);
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", String(t0 + 2));
    await expect(scrubber(page)).toHaveAttribute("aria-valuenow", String(t0 + 2));
    await page.getByRole("button", { name: en.reel.brain.pause }).click();
    await page.clock.runFor(2000);
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", String(t0 + 2));
  });

  test("hover links the Areas rows, the lanes and the brain", async ({ page }, info) => {
    await page.goto(URL);
    await openAreas(page);
    await brainReady(page);
    const c = canvas(page);
    const net1 = brain.atlas.order.filter((k) => brain.atlas.hcp.network[k] === 1);

    if (info.project.name === "laptop") {
      await page.locator('[data-area-id="net-1"]').hover();
      await expect(c).toHaveAttribute("data-hover-area", "net-1");
      await page.getByRole("button", { name: en.reel.areas.expand.replace("{network}", brain.atlas.yeo.labels[0]) }).click();
      const row = page.locator(`[data-area-id="hcp-${net1[2]}"]`);
      await row.hover();
      await expect(c).toHaveAttribute("data-hover-area", `hcp-${net1[2]}`);
      await page.mouse.move(0, 0);
      await expect(c).toHaveAttribute("data-hover-area", "");

      // The brain marks the row of the area under the pointer (no scrolling).
      await c.scrollIntoViewIfNeeded();
      const box = (await c.boundingBox())!;
      await page.mouse.move(box.x + box.width * 0.25, box.y + box.height * 0.5);
      const tip = page.locator('[data-brain-tooltip="float"]');
      await expect(tip).toBeVisible();
      await expect(tip).toHaveAttribute("data-layer", "brain");
      const id = (await c.getAttribute("data-hover-area"))!;
      expect(id).toMatch(/^hcp-\d+$/);
      const k = Number(id.slice(4));
      await expect(page.locator(`[data-area-id="net-${brain.atlas.hcp.network[k]}"]`)).toHaveAttribute("data-hover", "within");
      if (net1.includes(k)) await expect(page.locator(`[data-area-id="${id}"]`)).toHaveAttribute("data-hover", "left");
      await expect(tip).toContainText(brain.atlas.hcp.labels[k]);
      await page.mouse.move(0, 0);
      await expect(tip).toHaveCount(0);

      // A lane's name outlines that line's areas.
      await page.locator('[data-lane-label="seeing"]').hover();
      await expect(c).toHaveAttribute("data-hover-area", "line-seeing");
      await page.mouse.move(0, 0);
      await expect(c).toHaveAttribute("data-hover-area", "");
    } else {
      // Touch: a tap pins the area's card under the brain; a tap on a row pins it with "Show on brain".
      const box = (await c.boundingBox())!;
      await c.tap({ position: { x: box.width * 0.25, y: box.height * 0.5 } });
      const card = page.locator('[data-brain-tooltip="card"]');
      await expect(card).toBeVisible();
      await expect(card).toHaveAttribute("data-layer", "brain");
      const id = (await c.getAttribute("data-hover-area"))!;
      expect(id).toMatch(/^hcp-\d+$/);
      await expect(page.locator(`[data-area-id="net-${brain.atlas.hcp.network[Number(id.slice(4))]}"]`)).toHaveAttribute("data-hover", "within");
      await card.getByRole("button", { name: en.ui.close }).tap();
      await expect(card).toHaveCount(0);

      await page.locator('[data-area-id="net-1"] [data-layer="brain"]').first().tap();
      await expect(c).toHaveAttribute("data-hover-area", "net-1");
      await page.getByRole("button", { name: en.reel.areas.showOnBrain }).tap();
      await expect(c).toBeInViewport();
    }
  });

  test("Areas rows stay in atlas order at every second", async ({ page }) => {
    await page.goto(URL);
    await openAreas(page);
    for (const name of brain.atlas.yeo.labels) {
      await page.getByRole("button", { name: en.reel.areas.expand.replace("{network}", name) }).click();
    }
    await expect(page.locator('[data-chart="areas"] [data-area-id^="hcp-"]')).toHaveCount(180);
    const expected = brain.atlas.yeo.labels.flatMap((_, i) => [
      `net-${i + 1}`,
      ...brain.atlas.order.filter((k) => brain.atlas.hcp.network[k] === i + 1).map((k) => `hcp-${k}`),
    ]);

    const t0 = Number(await timeline(page).getAttribute("aria-valuenow"));
    const steps: Array<[string[], number]> = [
      [[], t0],
      [["PageUp", "PageUp", "ArrowRight", "ArrowRight", "ArrowRight"], t0 + 13],
      [["PageUp", "PageUp"], t0 + 23],
    ];
    for (const [keys, t] of steps) {
      await timeline(page).focus();
      for (const key of keys) await page.keyboard.press(key);
      await expect(timeline(page)).toHaveAttribute("aria-valuenow", String(t));
      expect(await rowIds(page)).toEqual(expected);
      const nets = await page.locator('[data-chart="areas"] [data-area-id^="net-"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-on")));
      expect(nets).toEqual(brain.areas.yeo.map((s) => onBrain(s[t])));
      const sides = await page
        .locator('[data-chart="areas"] [data-area-id^="hcp-"]')
        .evaluateAll((els) => els.map((e) => [e.getAttribute("data-area-id"), e.getAttribute("data-on-left"), e.getAttribute("data-on-right")]));
      expect(sides).toEqual(
        brain.atlas.order
          .slice()
          .sort((a, b) => brain.atlas.hcp.network[a] - brain.atlas.hcp.network[b] || brain.atlas.order.indexOf(a) - brain.atlas.order.indexOf(b))
          .map((k) => [`hcp-${k}`, onBrain(brain.areas.hcp_left[k][t]), onBrain(brain.areas.hcp_right[k][t])]),
      );
    }
    const text = await page.locator('[data-chart="areas"]').innerText();
    expect(banned(text)).toEqual([]);
    expect(text).not.toMatch(/#\d/);
    expect(text).not.toMatch(/(?<![\w.])\d+(?:st|nd|rd|th)(?![A-Za-z0-9])/);
  });

  test("numbers files: exact header, no count words, every row, real downloads", async ({ page }) => {
    const res = await page.request.get(`/reels/${SC}/brain/csv`);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toMatch(/^text\/csv/);
    expect(res.headers()["content-disposition"]).toBe(`attachment; filename="tribe-${SC}-${brain.job_id}-areas.csv"`);
    const csv = await res.text();
    const lines = csv.trimEnd().split("\n");
    const body = lines.filter((l) => !l.startsWith("# "));
    expect(lines[0]).toBe(`# ${en.reel.download.csv.footer}`);
    expect(body[0]).toBe(AREAS_HEADER);
    expect(body.length - 1).toBe(T * (4 + 7 + 360));
    expect(csv).not.toMatch(COUNT_TERMS_RE);
    expect(banned(csv)).toEqual([]);

    await page.goto(URL);
    const menu = page.locator('[data-chart="brain"] [data-download-menu]');
    await menu.click();
    const [areas] = await Promise.all([page.waitForEvent("download"), page.getByRole("menuitem", { name: en.reel.download.areas }).click()]);
    expect(areas.suggestedFilename()).toBe(`tribe-${SC}-${brain.job_id}-areas.csv`);

    await menu.click();
    const [surface] = await Promise.all([
      page.waitForEvent("download", { timeout: 25_000 }),
      page.getByRole("menuitem", { name: en.reel.download.surface }).click(),
    ]);
    expect(surface.suggestedFilename()).toBe(`tribe-${SC}-${brain.job_id}-surface.csv`);
    const text = readFileSync((await surface.path())!, "utf8");
    const rows = text.trimEnd().split("\n").filter((l) => !l.startsWith("# "));
    expect(rows[0]).toBe(`vertex,hemisphere,area,network,feeds_line,${brain.time_s.map((s) => `s${s}`).join(",")}`);
    expect(rows.length - 1).toBe(BRAIN.vertices);
    expect(rows[1].split(",")).toHaveLength(5 + T);
    expect(text).not.toMatch(COUNT_TERMS_RE);
    expect(text.split("\n")[0]).toBe(`# ${en.reel.download.csv.footer}`);
  });

  test("wall: no counts value in the timeline, the brain or the Areas tab", async ({ page }) => {
    await page.goto(URL);
    await brainReady(page);
    await expect(page.locator('#reel-timeline [data-layer="counts"]')).toHaveCount(0);
    await expect(page.locator('[data-chart="brain"] [data-layer="counts"]')).toHaveCount(0);
    await expect(page.locator('[data-chart="brain"] [data-layer="brain"]').first()).toBeAttached();
    await openAreas(page);
    await expect(page.locator('[data-chart="areas"] [data-layer="counts"]')).toHaveCount(0);
    await expect(page.locator('[data-chart="areas"] [data-layer="brain"]').first()).toBeAttached();
    // The two brain charts sit side by side, never one inside another or inside the timeline.
    const nested = await page.evaluate(() =>
      [...document.querySelectorAll("[data-chart]")].filter((c) => c.parentElement?.closest("[data-chart]")).map((c) => c.getAttribute("data-chart")),
    );
    expect(nested).toEqual([]);
  });

  test("reduced motion: nothing runs and Play never blends", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(URL);
    await brainReady(page);
    await page.waitForTimeout(50);
    const running = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length);
    expect(running).toBe(0);
    const c = canvas(page);
    const start = Number(await c.getAttribute("data-frame"));
    await page.getByRole("button", { name: en.reel.brain.play }).click();
    const mixes = new Set<string | null>();
    for (let i = 0; i < 14; i++) {
      mixes.add(await c.getAttribute("data-mix"));
      await page.waitForTimeout(100);
    }
    await expect(c).not.toHaveAttribute("data-frame", String(start));
    await page.getByRole("button", { name: en.reel.brain.pause }).click();
    expect([...mixes]).toEqual(["0"]);
  });

  test("no WebGL: the fallback, no errors, no sideways scroll", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) {
        if (/webgl/i.test(kind)) return null;
        return (original as (...a: unknown[]) => RenderingContext | null).call(this, kind, ...rest);
      } as typeof original;
    });
    await page.goto(URL);
    await page.locator('[data-chart="brain"]').scrollIntoViewIfNeeded();
    await expect(page.locator('[data-brain-fallback="none"]')).toBeVisible();
    await expect(page.locator('[data-brain-fallback="none"]')).toContainText(en.reel.brain.noWebgl);
    await expect(canvas(page)).toHaveCount(0);
    // The scrubber and the downloads still work without the 3D map.
    await scrubber(page).focus();
    await page.keyboard.press("ArrowRight");
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", String(Math.min(...tribe.peaks.filter((p) => !p.edge).map((p) => p.t)) + 1));
    await page.waitForLoadState("networkidle");
    await noSidewaysScroll(page);
    expect(errors).toEqual([]);
  });

  test("a lost context falls back and reloads", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(URL);
    await brainReady(page);
    await canvas(page).evaluate((el: HTMLCanvasElement) => (el.getContext("webgl2") as WebGL2RenderingContext).getExtension("WEBGL_lose_context")?.loseContext());
    await expect(page.locator('[data-brain-fallback="lost"]')).toBeVisible();
    await expect(page.locator('[data-brain-fallback="lost"]')).toContainText(en.reel.brain.lost);
    await expect(canvas(page)).toHaveCount(0);
    await page.getByRole("button", { name: en.reel.brain.reload }).click();
    await brainReady(page);
    expect(errors).toEqual([]);
  });

  test("phone: sideways drag turns, vertical swipe scrolls, 44px controls", async ({ page }, info) => {
    test.skip(info.project.name !== "phone", "touch gestures");
    await page.goto(URL);
    await brainReady(page);
    const c = canvas(page);
    await c.evaluate((el) => el.scrollIntoView({ block: "center" }));
    const cdp = await page.context().newCDPSession(page);
    const touch = async (from: [number, number], to: [number, number]) => {
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: from[0], y: from[1] }] });
      for (let i = 1; i <= 10; i++) {
        const p = { x: from[0] + ((to[0] - from[0]) * i) / 10, y: from[1] + ((to[1] - from[1]) * i) / 10 };
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [p] });
      }
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    };

    let box = (await c.boundingBox())!;
    const yaw0 = await c.getAttribute("data-yaw");
    await touch([box.x + box.width * 0.3, box.y + box.height * 0.5], [box.x + box.width * 0.75, box.y + box.height * 0.5]);
    await expect(c).not.toHaveAttribute("data-yaw", yaw0 ?? "0");

    box = (await c.boundingBox())!;
    const before = await page.evaluate(() => window.scrollY);
    await touch([box.x + box.width * 0.5, box.y + box.height * 0.8], [box.x + box.width * 0.5, box.y + box.height * 0.8 - 180]);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(before + 40);

    const controls = [
      page.getByRole("button", { name: en.reel.brain.play }),
      page.locator("[data-angle-button=outside]"),
      page.locator("[data-angle-button=inside]"),
      page.locator("[data-brain-reset]"),
      page.locator('[data-chart="brain"] [data-download-menu]'),
      scrubber(page),
    ];
    for (const el of controls) {
      const b = (await el.boundingBox())!;
      expect(b.height).toBeGreaterThanOrEqual(43.5);
    }
  });
});

test.describe("brain colours and frames (Node)", () => {
  test.skip(({ isMobile }) => isMobile, "pure functions: run once");

  test("one symmetric colour scale", () => {
    for (const u of [0, 0.05, 0.149, 0.15, 0.2, 0.33, 0.5, 0.75, 1]) {
      expect(alphaAt(u)).toBe(alphaAt(-u));
    }
    expect(alphaAt(0.1)).toBe(0);
    expect(alphaAt(0.5)).toBe(1);
    expect(alphaAt(1)).toBe(1);
    for (let i = 0; i < LUT_SIZE; i++) expect(lutU(i)).toBeCloseTo(-lutU(LUT_SIZE - 1 - i), 12);
    for (const pal of [DEFAULT_PALETTE.light, DEFAULT_PALETTE.dark]) {
      const lut = buildLut(pal);
      expect(lut).toEqual(buildLut(pal));
      // A colour depends on the value alone: the same u gives the same colour every time.
      for (const u of [-0.9, -0.4, 0, 0.4, 0.9]) expect(colorFor(u, pal.near, pal)).toEqual(colorFor(u, pal.near, pal));
      // Below the grey threshold only the grey shows, on both sides.
      expect(colorFor(0.1, pal.near, pal)).toEqual(pal.near);
      expect(colorFor(-0.1, pal.near, pal)).toEqual(pal.near);
      // Each arm keeps its hue and moves its lightness one way only.
      for (const sign of [-1, 1]) {
        const ls = [0, 0.25, 0.5, 0.75, 1].map((a) => rgbToOklch(poleColor(sign * a, pal))[0]);
        const diffs = ls.slice(1).map((l, i) => l - ls[i]);
        expect(diffs.every((d) => d <= 1e-6) || diffs.every((d) => d >= -1e-6)).toBe(true);
      }
      const hue = (rgb: [number, number, number]) => rgbToOklch(rgb)[2];
      expect(Math.abs(hue(poleColor(-0.8, pal)) - hue(pal.cool))).toBeLessThan(0.15);
      expect(Math.abs(hue(poleColor(0.8, pal)) - hue(pal.warm))).toBeLessThan(0.15);
    }
  });

  test("the frames decoder checks the header, the length and the levels", () => {
    const rows = 2;
    const make = (magic = "TBF1", q = -127) => {
      const b = new Uint8Array(BRAIN.headerBytes + rows * BRAIN.vertices);
      for (let i = 0; i < 4; i++) b[i] = magic.charCodeAt(i);
      const dv = new DataView(b.buffer);
      dv.setUint32(4, rows, true);
      dv.setUint32(8, BRAIN.vertices, true);
      dv.setUint32(12, BRAIN.levels, true);
      const body = new Int8Array(b.buffer, BRAIN.headerBytes);
      body[BRAIN.vertices + 5] = q;
      body[3] = 42;
      return b;
    };
    const f = decodeFrames(make(), rows);
    expect(f.rows).toBe(rows);
    expect(frameRow(f, 0)[3]).toBe(42);
    expect(frameRow(f, 1)[5]).toBe(-127);
    expect(frameRow(f, 99)[5]).toBe(-127);
    expect(() => decodeFrames(make("TBX1"), rows)).toThrow(BrainFormatError);
    expect(() => decodeFrames(make(), rows + 1)).toThrow(BrainFormatError);
    expect(() => decodeFrames(make().subarray(0, 100))).toThrow(BrainFormatError);
    expect(() => decodeFrames(make("TBF1", -128), rows)).toThrow(BrainFormatError);
  });
});
