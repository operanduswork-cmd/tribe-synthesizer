// The reel video (D30) in fixtures mode, at phone (390x844) and laptop (1280x800) widths.
// Fixtures mode has no videos: the test hook cookie (lib/data.ts VIDEO_TEST_COOKIE) gives a fixture
// reel a synthetic row so the player renders, and Playwright serves tests/assets/testclip.mp4 (a
// synthetic 6-second ffmpeg testsrc picture with a sine tone, never a real reel; outside web/'s
// deploy allowlist) in place of /reels/<sc>/video, answering Range requests the way the private
// Blob store does (206). Checks:
// - the player is its own figure (data-chart="video") with no counts and no brain values (D20),
//   plays inline, has our own controls (44px on a phone), sits first on a phone and on top of the
//   right column on a laptop, adds no banned words and no sideways scroll;
// - Play plays the video and the timeline, the brain slider and the brain frame follow it; the
//   brain's Pause stops the video (one action);
// - every seek (timeline keys, the brain slider, a time chip) moves the video to that second, and a
//   drag on the timeline pauses it;
// - an error asks the route again with a fresh query and goes back to the same time; after two
//   failures in a row a note and a retry button show, and Play falls back to the 1-s step;
// - reduced motion: it still plays, and nothing glides or blends;
// - the route itself: 404 in fixtures mode and for a malformed shortcode, never cached.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import en from "../copy/en.json";
import reel from "../fixtures/reel.json";

const SC = reel.shortcode;
const URL = `/reels/${SC}`;
const ROOT = path.resolve(__dirname, "..", "..");
const CLIP = path.resolve(__dirname, "assets", "testclip.mp4");
/** lib/data.ts VIDEO_TEST_COOKIE (that module is server-only, so the name is repeated here). */
const VIDEO_TEST_COOKIE = "tribe-test-video";
const V = en.reel.video;
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

/** The synthetic clip (root .gitignore drops *.mp4, so a fresh checkout makes it again). */
function ensureClip() {
  if (fs.existsSync(CLIP)) return;
  fs.mkdirSync(path.dirname(CLIP), { recursive: true });
  execFileSync("ffmpeg", [
    ...["-hide_banner", "-loglevel", "error", "-y"],
    ...["-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=30"],
    ...["-f", "lavfi", "-i", "sine=frequency=440:duration=6:sample_rate=44100"],
    ...["-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "baseline", "-crf", "30", "-g", "30", "-sc_threshold", "0"],
    ...["-c:a", "aac", "-b:a", "64k", "-shortest", "-movflags", "+faststart", "-map_metadata", "-1"],
    ...["-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact", CLIP],
  ]);
}

type Serve = { hits: string[] };

/** Turns the test hook on and serves the clip for /reels/<sc>/video, with Range (206) like the
 *  Blob store. `fail` answers the first n requests (or every one) with 503. */
async function withVideo(page: Page, fail: number | "all" = 0): Promise<Serve> {
  const baseURL = test.info().project.use.baseURL!;
  await page.context().addCookies([{ name: VIDEO_TEST_COOKIE, value: "1", url: baseURL }]);
  const bytes = fs.readFileSync(CLIP);
  const serve: Serve = { hits: [] };
  await page.route(/\/reels\/[^/]+\/video(\?.*)?$/, async (route) => {
    const req = route.request();
    serve.hits.push(req.url());
    if (fail === "all" || serve.hits.length <= fail) {
      return route.fulfill({ status: 503, headers: { "Cache-Control": "no-store" } });
    }
    const m = /bytes=(\d+)-(\d*)/.exec(req.headers()["range"] ?? "");
    if (!m) return route.fulfill({ status: 200, contentType: "video/mp4", headers: { "Accept-Ranges": "bytes" }, body: bytes });
    const start = Number(m[1]);
    const end = m[2] ? Math.min(Number(m[2]), bytes.length - 1) : bytes.length - 1;
    return route.fulfill({
      status: 206,
      contentType: "video/mp4",
      headers: { "Accept-Ranges": "bytes", "Content-Range": `bytes ${start}-${end}/${bytes.length}` },
      body: bytes.subarray(start, end + 1),
    });
  });
  return serve;
}

const figure = (page: Page) => page.locator('[data-chart="video"]');
const video = (page: Page) => figure(page).locator("video");
const timeline = (page: Page) => page.getByRole("slider", { name: en.reel.timeline.label });
const scrubber = (page: Page) => page.getByRole("slider", { name: en.reel.brain.second });
const canvas = (page: Page) => page.locator("[data-brain-canvas]");
const currentTime = (page: Page) => video(page).evaluate((v: HTMLVideoElement) => v.currentTime);
const paused = (page: Page) => video(page).evaluate((v: HTMLVideoElement) => v.paused);

async function videoReady(page: Page) {
  await expect(video(page)).toHaveCount(1);
  await expect.poll(() => video(page).evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 20_000 }).toBeGreaterThanOrEqual(1);
}

/** The video's time is this second, within half a second. */
async function videoAt(page: Page, s: number) {
  await expect.poll(() => currentTime(page), { timeout: 10_000 }).toBeGreaterThanOrEqual(s - 0.5);
  await expect.poll(() => currentTime(page), { timeout: 10_000 }).toBeLessThanOrEqual(s + 0.5);
}

async function brainReady(page: Page) {
  await page.locator('[data-chart="brain"]').scrollIntoViewIfNeeded();
  await expect(canvas(page)).toHaveAttribute("data-ready", "true", { timeout: 60_000 });
}

/** Presses a control as a reader does: a tap on a phone, a click on a laptop. */
async function press(page: Page, el: Locator) {
  if (test.info().project.name === "phone") await el.tap();
  else await el.click();
}

/** Puts the timeline at 0 with the keys (the page opens on the read's first HIGH, past the clip). */
async function toStart(page: Page) {
  await timeline(page).focus();
  await page.keyboard.press("Home");
  await expect(timeline(page)).toHaveAttribute("aria-valuenow", "0");
  await videoAt(page, 0);
}

test.beforeAll(() => ensureClip());

test.describe("reel video", () => {
  // The brain draws in software (SwiftShader) and the clip plays in real time.
  test.describe.configure({ timeout: 90_000 });

  test("its own figure: no counts or brain values, inline, own 44px controls, placed first", async ({ page }, info) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    await withVideo(page);
    await page.goto(URL);
    await videoReady(page);

    // One figure, a chart of its own (never inside another), named, holding no layer values.
    await expect(figure(page)).toHaveCount(1);
    await expect(figure(page)).toHaveAttribute("aria-label", V.label);
    expect(await figure(page).evaluate((f) => f.parentElement?.closest("[data-chart]") ?? null)).toBeNull();
    await expect(figure(page).locator('[data-layer="counts"]')).toHaveCount(0);
    await expect(figure(page).locator('[data-layer="brain"]')).toHaveCount(0);
    expect(await figure(page).locator("[data-layer]").evaluateAll((els) => [...new Set(els.map((e) => e.getAttribute("data-layer")))])).toEqual(["ui"]);

    // Plays inline (no full screen on a phone), loads only its metadata, our controls not the
    // browser's, and asks the site's own route (relative), never a storage link.
    const v = video(page);
    expect(await v.evaluate((el: HTMLVideoElement) => el.playsInline)).toBe(true);
    await expect(v).toHaveAttribute("playsinline", "");
    await expect(v).toHaveAttribute("preload", "metadata");
    expect(await v.evaluate((el: HTMLVideoElement) => el.controls)).toBe(false);
    expect(await v.getAttribute("src")).toBe(`/reels/${SC}/video`);
    expect(await v.evaluate((el: HTMLVideoElement) => el.currentSrc)).toMatch(new RegExp(`^https?://[^/]+/reels/${SC}/video$`));

    const play = figure(page).getByRole("button", { name: V.play, exact: true });
    const sound = figure(page).getByRole("button", { name: V.soundOff, exact: true });
    await expect(play).toBeVisible();
    await expect(sound).toBeVisible();
    if (info.project.name === "phone") {
      for (const el of [play, sound]) {
        const b = (await el.boundingBox())!;
        expect(b.height).toBeGreaterThanOrEqual(43.5);
        expect(b.width).toBeGreaterThanOrEqual(43.5);
      }
    }

    // The sound button mutes and unmutes the video.
    await press(page, sound);
    await expect(figure(page).getByRole("button", { name: V.soundOn, exact: true })).toBeVisible();
    expect(await v.evaluate((el: HTMLVideoElement) => el.muted)).toBe(true);
    await press(page, figure(page).getByRole("button", { name: V.soundOn, exact: true }));
    expect(await v.evaluate((el: HTMLVideoElement) => el.muted)).toBe(false);

    // Placement: first on a phone (before the card's tabs), on top of the right column on a
    // laptop (beside the tabs, above the brain).
    const fig = (await figure(page).boundingBox())!;
    const tabs = (await page.getByRole("tablist").boundingBox())!;
    const brain = (await page.locator('[data-chart="brain"]').boundingBox())!;
    if (info.project.name === "phone") {
      expect(fig.y + fig.height).toBeLessThanOrEqual(tabs.y);
    } else {
      expect(fig.x).toBeGreaterThan(tabs.x + tabs.width);
      expect(fig.y + fig.height).toBeLessThanOrEqual(brain.y);
    }

    const text = await page.locator("main").innerText();
    expect(banned(text)).toEqual([]);
    const [scroll, width] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    expect(scroll).toBeLessThanOrEqual(width);
    expect(errors).toEqual([]);
  });

  test("Play plays the video; the timeline, the brain slider and the brain frame follow", async ({ page }) => {
    await withVideo(page);
    await page.goto(URL);
    await videoReady(page);
    await brainReady(page);
    await toStart(page);
    await expect(canvas(page)).toHaveAttribute("data-frame", "0");

    await press(page, figure(page).getByRole("button", { name: V.play, exact: true }));
    await expect(figure(page).getByRole("button", { name: V.pause, exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: en.reel.brain.pause, exact: true })).toBeVisible();
    expect(await paused(page)).toBe(false);
    await expect.poll(async () => Number(await timeline(page).getAttribute("aria-valuenow")), { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
    await expect.poll(async () => Number(await canvas(page).getAttribute("data-frame")), { timeout: 15_000 }).toBeGreaterThanOrEqual(2);

    // The brain's Pause is the same action: the video stops, and every part shows its second.
    await press(page, page.getByRole("button", { name: en.reel.brain.pause, exact: true }));
    await expect.poll(() => paused(page)).toBe(true);
    await expect(figure(page).getByRole("button", { name: V.play, exact: true })).toBeVisible();
    const s = Math.floor((await currentTime(page)) + 1e-3);
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", String(s));
    await expect(scrubber(page)).toHaveAttribute("aria-valuenow", String(s));
    await expect(canvas(page)).toHaveAttribute("data-frame", String(s));
    await expect(page.locator(`[data-playhead="${s}"]`)).toHaveCount(1);

    // The brain's Play plays the video too, and it stops at the clip's end.
    await press(page, page.getByRole("button", { name: en.reel.brain.play, exact: true }));
    await expect.poll(() => paused(page)).toBe(false);
    await expect.poll(() => video(page).evaluate((v: HTMLVideoElement) => v.ended), { timeout: 20_000 }).toBe(true);
    await expect(page.getByRole("button", { name: en.reel.brain.play, exact: true })).toBeVisible();
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", "6");
  });

  test("seeking the timeline, the brain slider or a chip moves the video; a drag pauses it", async ({ page }) => {
    await withVideo(page);
    await page.goto(URL);
    await videoReady(page);
    await toStart(page);

    for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", "3");
    await videoAt(page, 3);

    await scrubber(page).focus();
    await page.keyboard.press("ArrowLeft");
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", "2");
    await videoAt(page, 2);

    // A time chip on the card (HOOK, 0:00) and one in the Beats tab (0:03-0:11).
    await timeline(page).focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await videoAt(page, 4);
    const hook = reel.card.lines.find((l) => l.tag === "HOOK")!;
    await press(page, page.locator('li[data-tag="HOOK"]').getByRole("button", { name: hook.time!, exact: true }));
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", String(hook.t));
    await videoAt(page, hook.t!);
    await press(page, page.getByRole("tab", { name: en.reel.tabs.beats }));
    await press(page, page.getByRole("button", { name: "0:03-0:11", exact: true }).first());
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", "3");
    await videoAt(page, 3);

    // While playing a key seek keeps playing from the new second; a drag pauses.
    await press(page, figure(page).getByRole("button", { name: V.play, exact: true }));
    await expect.poll(() => paused(page)).toBe(false);
    await timeline(page).focus();
    await page.keyboard.press("Home");
    await expect.poll(() => currentTime(page)).toBeLessThan(1.5);
    expect(await paused(page)).toBe(false);
    const box = (await timeline(page).boundingBox())!;
    await page.mouse.move(box.x + box.width * (4.5 / 42.3), box.y + 8);
    await page.mouse.down();
    await page.mouse.up();
    await expect.poll(() => paused(page)).toBe(true);
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", "4");
    await videoAt(page, 4);
  });

  test("an error asks again and goes back to the same time", async ({ page }) => {
    const serve = await withVideo(page);
    await page.goto(URL);
    await videoReady(page);
    await toStart(page);
    for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
    await videoAt(page, 3);
    const before = serve.hits.length;

    await video(page).evaluate((v: HTMLVideoElement) => v.dispatchEvent(new Event("error")));
    // A fresh request with a cache-busting query, then back to 0:03 once loaded.
    await expect.poll(() => serve.hits.slice(before).some((u) => /\/video\?r=/.test(u))).toBe(true);
    await expect.poll(() => video(page).evaluate((v: HTMLVideoElement) => v.currentSrc)).toMatch(/\/video\?r=/);
    await videoReady(page);
    await videoAt(page, 3);
    await expect(timeline(page)).toHaveAttribute("aria-valuenow", "3");
    await expect(figure(page).locator("[data-video-failed]")).toHaveCount(0);
  });

  test("a first load that fails is retried", async ({ page }) => {
    const serve = await withVideo(page, 1);
    await page.goto(URL);
    await videoReady(page);
    expect(serve.hits.length).toBeGreaterThanOrEqual(2);
    expect(serve.hits.slice(1).every((u) => /\/video\?r=/.test(u))).toBe(true);
    await expect(figure(page).locator("[data-video-failed]")).toHaveCount(0);
    await toStart(page);
    await page.keyboard.press("ArrowRight");
    await videoAt(page, 1);
  });

  test("after two failed retries: a note, a retry button, and Play steps without the video", async ({ page }, info) => {
    const serve = await withVideo(page, "all");
    await page.goto(URL);
    const failed = figure(page).locator("[data-video-failed]");
    await expect(failed).toBeVisible({ timeout: 20_000 });
    await expect(failed).toContainText(V.failed);
    expect(serve.hits.length).toBe(3);
    const retry = failed.getByRole("button", { name: V.retry, exact: true });
    if (info.project.name === "phone") expect((await retry.boundingBox())!.height).toBeGreaterThanOrEqual(43.5);

    // The brain's Play falls back to stepping a second a second.
    const t0 = Number(await timeline(page).getAttribute("aria-valuenow"));
    await press(page, page.getByRole("button", { name: en.reel.brain.play, exact: true }));
    await expect.poll(async () => Number(await timeline(page).getAttribute("aria-valuenow")), { timeout: 5_000 }).toBeGreaterThan(t0);
    await press(page, page.getByRole("button", { name: en.reel.brain.pause, exact: true }));

    // Retry asks once more.
    await press(page, retry);
    await expect.poll(() => serve.hits.length).toBeGreaterThan(3);
  });

  test("reduced motion: it still plays; nothing glides or blends", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await withVideo(page);
    await page.goto(URL);
    await videoReady(page);
    await brainReady(page);
    await toStart(page);
    await press(page, figure(page).getByRole("button", { name: V.play, exact: true }));
    const mixes = new Set<string | null>();
    for (let i = 0; i < 25; i++) {
      mixes.add(await canvas(page).getAttribute("data-mix"));
      await page.waitForTimeout(100);
    }
    expect(Number(await timeline(page).getAttribute("aria-valuenow"))).toBeGreaterThanOrEqual(1);
    const glide = await page.locator("[data-playhead]").evaluate((el) => parseFloat(getComputedStyle(el).transitionDuration));
    expect(glide).toBeLessThanOrEqual(0.001);
    await press(page, figure(page).getByRole("button", { name: V.pause, exact: true }));
    expect([...mixes]).toEqual(["0"]);
  });
});

test.describe("reel video route", () => {
  test.skip(({ isMobile }) => isMobile, "server responses: run once");

  test("404 in fixtures mode and for a malformed shortcode, never cached, no link", async ({ request }) => {
    const baseURL = test.info().project.use.baseURL!;
    for (const [url, cookie] of [
      [`/reels/${SC}/video`, ""],
      [`/reels/${SC}/video`, `${VIDEO_TEST_COOKIE}=1`],
      ["/reels/abc/video", ""],
      ["/reels/a.b.c.d.e/video", ""],
    ] as const) {
      const res = await request.get(new globalThis.URL(url, baseURL).toString(), {
        maxRedirects: 0,
        headers: cookie ? { cookie } : {},
      });
      expect(res.status(), url).toBe(404);
      expect(res.headers()["cache-control"]).toBe("private, no-store");
      expect(res.headers()["location"]).toBeUndefined();
    }
  });
});
