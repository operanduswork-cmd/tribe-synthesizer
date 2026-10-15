// Shell smoke test in fixtures mode, at phone and laptop widths: the layout sizes, the licence
// footer, data-layer on values, the wall over the whole document (the shell included), the
// freshness lines, the runner status word, 44px touch targets on a phone, the palette, and no
// console errors. Round 2: the top bar never repeats a top-level page's H1 (detail pages keep
// their trail), the current nav item wears the indigo selection accent while text stays ink, and a
// route change crossfades through a view transition (none under reduced motion) with no errors.
// Round 3 (D30, less text): the footer is one short line whose (i) opens to exactly the full
// LICENCE 12 A text, links kept, on every page; freshness is one small "Data · <day>" line whose
// (i) opens to the four layer sentences, one line per layer, each with its own data-layer.

import { expect, test, type Locator, type Page } from "@playwright/test";

import en from "../copy/en.json";
import meta from "../fixtures/meta.json";

const PAGES = [
  "/board",
  "/patterns",
  "/export",
  "/settings/jobs",
  "/reels/DEMO0000001",
  "/reels/DEMO0000002",
];

/** A footer template filled in the way the page shows it (LICENCE 12 A; test_web_copy checks the doc). */
const footerText = (template: string) =>
  template.replace("{tribe}", en.footer.tribe).replace("{licence}", en.footer.licence).replace("{llama}", en.footer.llama);
const FOOTER_LINKS = [
  [en.footer.tribe, en.footer.tribeUrl],
  [en.footer.licence, en.footer.licenceUrl],
  [en.footer.llama, en.footer.llamaUrl],
] as const;

/** Opens an (i) hint by touch on a phone (checking its 44px hit area) or by click on a laptop. */
async function openHint(page: Page, trigger: Locator, phone: boolean) {
  if (phone) {
    const hit = await trigger.evaluate((el) => {
      const s = getComputedStyle(el, "::before");
      return Math.min(parseFloat(s.width), parseFloat(s.height));
    });
    expect(hit).toBeGreaterThanOrEqual(44);
    await trigger.tap();
  } else {
    await trigger.click();
  }
  const hint = page.locator('[data-hint][data-layer="ui"]');
  await expect(hint).toBeVisible();
  return hint;
}

/** A visible counts value and brain value that meet in one row, card or line container, or on
 *  one visual line inside a container no taller than a line (D20), anywhere in the document. */
async function lineBreaks(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const shown = (el: Element) => {
      const b = el.getBoundingClientRect();
      return b.width > 0 && b.height > 0 && getComputedStyle(el).visibility !== "hidden";
    };
    const counts = [...document.querySelectorAll('[data-layer="counts"]')].filter(shown);
    const brain = [...document.querySelectorAll('[data-layer="brain"]')].filter(shown);
    const out: string[] = [];
    for (const a of counts) {
      for (const b of brain) {
        let lca = a.parentElement;
        while (lca && !lca.contains(b)) lca = lca.parentElement;
        if (!lca) continue;
        const [ra, rb] = [a.getBoundingClientRect(), b.getBoundingClientRect()];
        const oneLine = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top) > 2;
        const lineBox = lca.getBoundingClientRect().height <= 48;
        if (lca.matches("li, tr, p, [data-row], [data-line], [data-sc], [role=row]") || (oneLine && lineBox)) {
          out.push(`${lca.tagName}: "${(a.textContent ?? "").slice(0, 30)}" + "${(b.textContent ?? "").slice(0, 30)}"`);
        }
      }
    }
    return out;
  });
}

/** Visible controls under 44px tall on touch, counting a transparent ::before hit area. */
async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    const sel = "a[href], button, summary, [role=switch], [role=tab], input, textarea, select";
    for (const el of document.querySelectorAll<HTMLElement>(sel)) {
      const b = el.getBoundingClientRect();
      if (!b.width || !b.height || el.closest("footer") || el.matches(".sr-only, a[href='#main']")) continue;
      let h = b.height;
      // A hit area in ::before/::after counts unless the control clips its own overflow.
      const clips = getComputedStyle(el).overflow !== "visible";
      for (const ps of clips ? [] : ["::before", "::after"]) {
        const cs = getComputedStyle(el, ps);
        if (cs.content !== "none" && cs.position === "absolute") h = Math.max(h, parseFloat(cs.height) || 0);
      }
      if (h < 43.5) out.push(`${el.tagName.toLowerCase()} "${(el.innerText || el.getAttribute("aria-label") || "").trim().slice(0, 30)}" ${Math.round(h)}px`);
    }
    return out;
  });
}

for (const path of PAGES) {
  test(`shell on ${path}`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(path);

    // The footer shows one short line with its three links; the full text waits behind its (i).
    const footer = page.locator("footer[data-licence]");
    await expect(footer.locator("[data-licence-line]")).toHaveText(footerText(en.footer.short));
    await expect(footer).toContainText(en.footer.llama);
    await expect(footer).toContainText("CC BY-NC 4.0");
    for (const [name, href] of FOOTER_LINKS) {
      await expect(footer.locator("[data-licence-line]").getByRole("link", { name, exact: true })).toHaveAttribute("href", href);
    }
    expect(await footer.innerText()).not.toContain("predicted average-brain response");

    // No counts value holds a brain value or the other way round, and none share a line (D20).
    await expect(page.locator('[data-layer="counts"] [data-layer="brain"], [data-layer="brain"] [data-layer="counts"]')).toHaveCount(0);
    expect(await lineBreaks(page)).toEqual([]);

    if (info.project.name === "laptop") {
      const aside = page.locator('[data-shell="sidebar"]');
      await expect(aside).toBeVisible();
      expect((await aside.boundingBox())?.width).toBe(232);
      expect((await page.locator('[data-shell="topbar"]').boundingBox())?.height).toBe(48);
      await expect(page.locator('[data-shell="tabbar"]')).toBeHidden();
    } else {
      await expect(page.locator('[data-shell="sidebar"]')).toBeHidden();
      await expect(page.locator('[data-shell="tabbar"]')).toBeVisible();
      await page.waitForLoadState("networkidle");
      expect(await smallTargets(page)).toEqual([]);
    }

    // The footer's (i) opens to exactly the LICENCE 12 A text (framing included), links kept.
    const trigger = footer.getByRole("button", { name: en.footer.hint, exact: true });
    await expect(trigger).toHaveCount(1);
    const hint = await openHint(page, trigger, info.project.name === "phone");
    await expect(hint.locator("[data-licence-text]")).toHaveText(footerText(en.footer.text));
    await expect(hint).toContainText("predicted average-brain response");
    for (const [name, href] of FOOTER_LINKS) {
      await expect(hint.getByRole("link", { name, exact: true })).toHaveAttribute("href", href);
    }
    expect(await lineBreaks(page)).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(hint).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

test("freshness: one small line; its (i) opens to one line per layer, never two layers on one line", async ({ page }, info) => {
  await page.goto("/board");
  const layers = ["counts", "facts", "shape", "brain"] as const;
  const phone = info.project.name === "phone";
  const line = page.locator(phone ? '[data-freshness="line"]' : '[data-shell="sidebar"] [data-freshness="sidebar"]');
  await expect(line).toBeVisible();
  await expect(line).toHaveAttribute("data-layer", "ui");

  // In view: only "Data · <render day>" (a ui date), no layer sentence and no layer value.
  const day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(meta.rendered_at));
  await expect(line.locator("[data-freshness-label]")).toHaveText(en.freshness.short.replace("{date}", day));
  await expect(line.locator("[data-layer]:not([data-layer=ui])")).toHaveCount(0);
  await expect(page.locator('[data-freshness="list"]')).toHaveCount(0);
  for (const l of layers) await expect(line.getByText(meta.layers[l].text)).toHaveCount(0);
  await expect(page.locator('[data-shell="topbar"] [data-layer="counts"], [data-shell="topbar"] [data-layer="brain"]')).toHaveCount(0);
  if (phone) expect((await line.boundingBox())!.height).toBeLessThanOrEqual(46);

  // The (i) opens to exactly the four sentences, one per line, each line its own layer.
  const trigger = line.getByRole("button", { name: en.topbar.freshness, exact: true });
  await expect(trigger).toHaveCount(1);
  const hint = await openHint(page, trigger, phone);
  const lines = hint.locator('[data-freshness="list"] > li');
  await expect(lines).toHaveText(layers.map((l) => meta.layers[l].text));
  expect(await lines.evaluateAll((els) => els.map((e) => e.getAttribute("data-layer")))).toEqual([...layers]);
  const tops = await lines.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().top));
  expect(new Set(tops).size).toBe(layers.length);
  await expect(hint.locator('[data-layer="counts"] [data-layer="brain"], [data-layer="brain"] [data-layer="counts"]')).toHaveCount(0);
  expect(await lineBreaks(page)).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(hint).toHaveCount(0);
});

test("runner status says its word at every width", async ({ page }) => {
  await page.goto("/board");
  const status = page.locator('[data-shell="topbar"] [data-runner-status]:visible');
  await expect(status).toHaveCount(1);
  await expect(status).toContainText(en.runner.fixtures);
});

test("palette opens with the keyboard and goes to a page", async ({ page }, info) => {
  test.skip(info.project.name !== "laptop", "keyboard shortcut is a laptop feature");
  await page.goto("/board");
  await page.waitForLoadState("networkidle");
  const input = page.getByPlaceholder(en.palette.placeholder);
  // The key handler is attached after hydration: press until the palette opens (only when it is closed, so it never toggles shut).
  await expect(async () => {
    if (!(await input.isVisible())) await page.keyboard.press("Control+k");
    await expect(input).toBeVisible({ timeout: 1500 });
  }).toPass({ timeout: 10_000 });
  await page.keyboard.type(en.nav.patterns);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/patterns$/);
});

// D31 (analysis only): the Script lab is gone from the nav and the palette, and old links land on the board.
test("nav: Board, Patterns, Export, Settings, in that order, and no Script lab", async ({ page }, info) => {
  await page.goto("/board");
  const nav = page.locator(info.project.name === "laptop" ? '[data-shell="sidebar"]' : '[data-shell="tabbar"]');
  await expect(nav.locator("a[href]:not([data-app-mark])")).toHaveText([en.nav.board, en.nav.patterns, en.nav.export, en.nav.settings]);
  await expect(nav.locator('a[href^="/lab"]')).toHaveCount(0);
});

// ---------------------------------------------------------------- round 2: top bar, nav, motion

const TOP_LEVEL = [
  { path: "/board", h1: en.pages.board.title },
  { path: "/patterns", h1: en.pages.patterns.title },
  { path: "/export", h1: en.pages.export.title },
  { path: "/settings/jobs", h1: en.pages.jobs.title },
];

for (const { path, h1 } of TOP_LEVEL) {
  test(`top bar on ${path}: the H1 names the page once, no bar label`, async ({ page }, info) => {
    await page.goto(path);
    await expect(page.locator("main h1").first()).toHaveText(h1);
    const bar = page.locator('[data-shell="topbar"]');
    await expect(bar.locator("[data-crumbs]")).toHaveCount(0);
    expect(await bar.innerText()).not.toContain(h1);
    // The phone bar shows the app mark instead (the sidebar that carries it is hidden there).
    if (info.project.name === "laptop") await expect(bar.locator("[data-app-mark]")).toBeHidden();
    else await expect(bar.locator("[data-app-mark]")).toContainText(en.app.name);
  });
}

for (const { path, parent, href, last } of [
  { path: "/reels/DEMO0000001", parent: en.nav.board, href: "/board", last: "DEMO0000001" },
]) {
  test(`top bar on ${path}: a detail page keeps its trail`, async ({ page }, info) => {
    await page.goto(path);
    const crumbs = page.locator('[data-shell="topbar"] [data-crumbs]');
    if (info.project.name === "laptop") {
      await expect(crumbs.locator(`ol a[href="${href}"]`)).toHaveText(parent);
      await expect(crumbs.locator('[aria-current="page"]')).toHaveText(last);
    } else {
      await expect(crumbs.getByRole("link", { name: en.topbar.back.replace("{page}", parent) })).toBeVisible();
      await expect(crumbs.locator("ol")).toBeHidden();
    }
  });
}

/** The computed colour of a CSS colour token, through a throwaway element. */
const tokenColour = (page: Page, token: string) =>
  page.evaluate((t) => {
    const probe = document.createElement("span");
    probe.style.color = `var(${t})`;
    document.body.append(probe);
    const c = getComputedStyle(probe).color;
    probe.remove();
    return c;
  }, token);

test("nav: the current page wears the indigo selection accent, text stays ink", async ({ page }, info) => {
  await page.goto("/patterns");
  const laptop = info.project.name === "laptop";
  const nav = page.locator(laptop ? '[data-shell="sidebar"]' : '[data-shell="tabbar"]');
  const current = nav.locator('a[aria-current="page"]');
  await expect(current).toHaveCount(1);
  await expect(current).toHaveAttribute("href", "/patterns");
  // One rail, on the current item only.
  await expect(nav.locator("[data-nav-rail]")).toHaveCount(1);
  await expect(current.locator("[data-nav-rail]")).toHaveCount(1);

  const [indigo, ink, muted, subtle] = await Promise.all(
    ["--indigo", "--text", "--text-muted", "--subtle"].map((t) => tokenColour(page, t)),
  );
  const look = (a: HTMLElement) => {
    const rail = a.querySelector("[data-nav-rail]");
    return {
      label: getComputedStyle(a).color,
      fill: getComputedStyle(a).backgroundColor,
      icon: getComputedStyle(a.querySelector("svg")!).color,
      rail: rail ? getComputedStyle(rail).backgroundColor : null,
    };
  };
  const on = await current.evaluate(look);
  expect(on.rail).toBe(indigo);
  expect(on.icon).toBe(indigo);
  expect(on.label).toBe(ink);

  // Another item: muted until hovered, then a grey fill and ink (laptop: hover is a mouse thing).
  const other = nav.locator('a[href="/board"]');
  expect((await other.evaluate(look)).label).toBe(muted);
  if (laptop) {
    await other.hover();
    await expect.poll(async () => other.evaluate(look)).toEqual({ label: ink, fill: subtle, icon: ink, rail: null });
  }
});

type VtRecord = { anims: number; names: string[] };

/** Records every view transition the page starts and, once it is ready, its visible animations
 *  (React also parks two 0 ms placeholder animations on the root; those are not motion). */
async function watchViewTransitions(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __vt: VtRecord[] };
    w.__vt = [];
    const start = document.startViewTransition?.bind(document);
    if (!start) return;
    document.startViewTransition = ((arg?: Parameters<typeof start>[0]) => {
      const vt = start(arg);
      const rec: VtRecord = { anims: -1, names: [] };
      w.__vt.push(rec);
      vt.ready.then(
        () => {
          const pseudo = (a: Animation) => (a.effect as KeyframeEffect | null)?.pseudoElement ?? "";
          const running = document
            .getAnimations()
            .filter((a) => pseudo(a).startsWith("::view-transition") && Number(a.effect?.getComputedTiming().duration) > 1);
          rec.anims = running.length;
          rec.names = [...new Set(running.map(pseudo))];
        },
        () => {},
      );
      return vt;
    }) as typeof document.startViewTransition;
  });
  return (from: number) => page.evaluate((b) => (window as unknown as { __vt: VtRecord[] }).__vt.slice(b), from);
}

const vtCount = (page: Page) => page.evaluate(() => (window as unknown as { __vt: VtRecord[] }).__vt.length);

test("route change: the page crossfades, the bars stay on top, the rail glides, no console errors", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  const since = await watchViewTransitions(page);
  await page.goto("/board");
  await page.waitForLoadState("networkidle");

  const laptop = info.project.name === "laptop";
  const nav = page.locator(laptop ? '[data-shell="sidebar"]' : '[data-shell="tabbar"]');
  const names = new Set<string>();
  for (const { path, h1 } of [...TOP_LEVEL.slice(1), TOP_LEVEL[0]]) {
    const before = await vtCount(page);
    await nav.locator(`a[href="${path}"]`).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page.locator("main h1").first()).toHaveText(h1);
    await expect(nav.locator('a[aria-current="page"]')).toHaveAttribute("href", path);
    await expect
      .poll(async () => (await since(before)).some((r) => r.anims > 0), { message: `a view transition into ${path}` })
      .toBe(true);
    for (const r of await since(before)) r.names.forEach((n) => names.add(n));
  }
  // The bars are their own groups (painted above the fading page), and the rail moves as one.
  const bar = laptop ? "shell-topbar" : "shell-tabbar";
  const rail = laptop ? "shell-nav-rail" : "shell-tab-rail";
  expect([...names]).toEqual(expect.arrayContaining([`::view-transition-group(${bar})`, `::view-transition-group(${rail})`]));
  expect(errors).toEqual([]);
});

test("route change under reduced motion: the page swaps at once", async ({ page }, info) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const since = await watchViewTransitions(page);
  await page.goto("/board");
  await page.waitForLoadState("networkidle");
  const nav = page.locator(info.project.name === "laptop" ? '[data-shell="sidebar"]' : '[data-shell="tabbar"]');
  const before = await vtCount(page);
  await nav.locator('a[href="/patterns"]').click();
  await expect(page.locator("main h1").first()).toHaveText(en.pages.patterns.title);
  await expect.poll(async () => (await since(before)).filter((r) => r.anims >= 0).length).toBeGreaterThan(0);
  for (const r of await since(before)) expect(r.anims, "view-transition animations under reduced motion").toBeLessThanOrEqual(0);
});

// Round 5: a one-click sun/moon toggle in the top bar, on every top-level page.
test.describe("theme toggle", () => {
  const TOP_LEVEL = ["/board", "/patterns", "/export", "/settings/jobs"];
  const toggle = (page: Page) => page.locator('[data-shell="topbar"] [data-theme-toggle]');

  for (const path of TOP_LEVEL) {
    test(`appears in the top bar on ${path}`, async ({ page }) => {
      await page.goto(path);
      await expect(toggle(page)).toBeVisible();
    });
  }

  test("flips the html class, keeps the choice after a reload, and is named by the action", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/board");
    const html = page.locator("html");
    await expect(html).toHaveClass(/dark/);
    await expect(toggle(page)).toHaveAttribute("aria-label", en.menu.light);

    await toggle(page).click();
    await expect(html).toHaveClass(/light/);
    await expect(html).not.toHaveClass(/dark/);
    await expect(toggle(page)).toHaveAttribute("aria-label", en.menu.dark);
    expect(await page.evaluate(() => localStorage.getItem("theme"))).toBe("light");

    await page.reload();
    await expect(html).toHaveClass(/light/);
    await expect(html).not.toHaveClass(/dark/);

    await toggle(page).click();
    await expect(html).toHaveClass(/dark/);
    expect(await page.evaluate(() => localStorage.getItem("theme"))).toBe("dark");
  });

  test("tap target is at least 44px on a phone", async ({ page }, info) => {
    test.skip(info.project.name !== "phone", "touch target is a phone check");
    await page.goto("/board");
    const hit = await toggle(page).evaluate((el) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el, "::before");
      return { w: Math.max(r.width, parseFloat(s.width)), h: Math.max(r.height, parseFloat(s.height)) };
    });
    expect(hit.w).toBeGreaterThanOrEqual(44);
    expect(hit.h).toBeGreaterThanOrEqual(44);
  });
});
