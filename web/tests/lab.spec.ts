// D31 (analysis only): the Script lab is removed from the site. /lab and any /lab/<id> link land
// on the board. (Its jobs tests moved to settings.spec.ts.)

import { expect, test } from "@playwright/test";

import en from "../copy/en.json";

for (const from of ["/lab", "/lab/20261009-demo-tool-explainer"]) {
  test(`${from} lands on /board`, async ({ page }) => {
    await page.goto(from);
    await expect(page).toHaveURL(/\/board$/);
    await expect(page.locator("main h1").first()).toHaveText(en.pages.board.title);
  });
}
