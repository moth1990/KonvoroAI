import { defineConfig, devices } from "@playwright/test";

// E2E has its own ports, so a running `make dev` (5180 / 8000) is never reused by mistake.
const webPort = Number(process.env.KONBORO_E2E_WEB_PORT ?? 5181);
const apiPort = Number(process.env.KONBORO_E2E_API_PORT ?? 8001);
const baseURL = `http://localhost:${webPort}`;
const apiURL = `http://127.0.0.1:${apiPort}`;

// Every UI test runs on both projects (CLAUDE.md, testing rules).
export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["fidelity/**"],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: { baseURL, locale: "he-IL", timezoneId: "Asia/Jerusalem", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    {
      name: "mobile",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true },
    },
  ],
  webServer: [
    {
      // Recreates the konboro_e2e database, seeds the E2E tenants, serves the API (needs `make up`).
      command: "uv run python -m konboro.devtools.e2e",
      cwd: "../backend",
      url: `${apiURL}/health`,
      env: { KONBORO_E2E_API_PORT: String(apiPort), KONBORO_E2E_WEB_PORT: String(webPort) },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `pnpm exec vite --port ${webPort} --strictPort`,
      url: baseURL,
      env: { VITE_API_URL: apiURL },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
