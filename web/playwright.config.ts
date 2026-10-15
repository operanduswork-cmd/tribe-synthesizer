// Playwright reuses the installed Chrome (channel "chrome"): no browser downloads.
// Runs against `next start` in fixtures mode at phone (390px) and laptop (1280px) widths.
// WebGL runs on SwiftShader (software) so the 3D brain draws headless on any machine; the
// no-WebGL fallback is tested by switching WebGL off in the page (tests/brain.spec.ts).

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  retries: 0,
  // SwiftShader WebGL is heavy: with more workers, page loads time out on a busy laptop.
  workers: 2,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    channel: "chrome",
    trace: "off",
    launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] },
  },
  projects: [
    { name: "phone", use: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
    { name: "laptop", use: { viewport: { width: 1280, height: 800 } } },
  ],
  webServer: {
    command: "npm run start -- -p 3100 -H 127.0.0.1",
    url: "http://127.0.0.1:3100/board",
    reuseExistingServer: true,
    timeout: 120_000,
    env: { TRIBE_DATA_SOURCE: "fixtures" },
  },
});
