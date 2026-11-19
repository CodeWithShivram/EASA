import { defineConfig, devices } from "@playwright/test";

import { API_PORT, WEB_PORT } from "./e2e/config.mjs";

/**
 * Browser end-to-end tests (P8-M3): the real web app (`next start`, so run
 * `npm run build` first) against the real API with a fresh database, the fake
 * chat model and the hashing embedder (e2e/stack.mjs). Tests share that
 * database, so they run one at a time.
 *
 * Browser: Playwright's Chromium (`npx playwright install chromium`); set
 * EASA_E2E_CHANNEL=msedge or chrome to use an installed browser instead.
 */
const channel = process.env.EASA_E2E_CHANNEL || undefined;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    // Traces record what the tests type, including the generated passwords of the
    // throwaway users, so they are kept only on a developer's machine.
    trace: process.env.CI ? "off" : "retain-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /\.setup\.ts$/, use: { ...devices["Desktop Chrome"], channel } },
    {
      name: "desktop",
      testMatch: /\.spec\.ts$/,
      testIgnore: /phone\.spec\.ts$/,
      dependencies: ["setup"],
      use: { ...devices["Desktop Chrome"], channel },
    },
    {
      name: "phone",
      testMatch: /phone\.spec\.ts$/,
      dependencies: ["setup"],
      use: { ...devices["Pixel 7"], channel },
    },
  ],
  webServer: [
    {
      command: "node e2e/stack.mjs",
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: `npx next start --hostname localhost --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/login`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { EASA_API_URL: `http://127.0.0.1:${API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
    },
  ],
});
