// Import demo (16 Oct): made-up results from pasted links, in four separate boxes, no job and no network write.

import { expect, test } from "@playwright/test";

import en from "../copy/en.json";

test("import demo: links in, four separate boxes out, same link same demo, nothing posted", async ({ page }) => {
  test.setTimeout(90_000);
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() !== "GET") posts.push(r.url());
  });
  await page.goto("/import");
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1")).toHaveText(en.pages.import.title);
  await expect(page.locator("[data-import-banner]")).toHaveText(en.import.banner);
  await expect(page.locator("[data-import-reel]")).toHaveCount(0);

  const input = page.locator("[data-import-input]");
  const run = page.locator("[data-import-run]");
  await expect(async () => {
    await input.fill("https://www.instagram.com/reel/DEMOabc1234/ https://www.instagram.com/reel/DEMOxyz5678/?igsh=1\nnot a link");
    await run.click();
    await expect(page.locator("[data-import-reel]")).toHaveCount(2, { timeout: 2000 });
  }).toPass({ timeout: 40_000 });

  const first = page.locator('[data-import-reel="DEMOabc1234"]');
  for (const layer of ["facts", "counts", "shape", "brain"]) await expect(first.locator(`[data-import-box="${layer}"]`)).toHaveCount(1);
  await expect(first.locator('[data-import-box="brain"] li')).toHaveCount(7);
  // Counts never sit inside the brain box (D20).
  await expect(first.locator('[data-import-box="brain"]')).not.toContainText(en.import.plays);
  const a = await first.innerText();
  await run.click();
  expect(await page.locator('[data-import-reel="DEMOabc1234"]').innerText()).toBe(a);

  await input.fill("nothing here");
  await run.click();
  await expect(page.getByText(en.import.noLinks)).toBeVisible();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "no horizontal page scroll").toBeLessThanOrEqual(0);
  expect(posts.filter((u) => /import|runner|jobs/.test(u) && !u.includes("_next")), "no write requests").toEqual([]);
});

test("import demo: the old redirect is gone and Export links here", async ({ page }) => {
  await page.goto("/export");
  await page.waitForLoadState("networkidle");
  await expect(async () => {
    await page.locator("[data-export-import]").click();
    await expect(page).toHaveURL(/\/import$/, { timeout: 3000 });
  }).toPass({ timeout: 30_000 });
});
