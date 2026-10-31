import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.KONBORO_WEB_PORT ?? 5180);
const baseURL = `http://localhost:${port}`;

// Every UI test runs on both projects (CLAUDE.md, testing rules).
export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["fidelity/**"],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: { baseURL, locale: "he-IL", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    {
      name: "mobile",
      use: { ...devices["Desktop Chrome"], viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true },
    },
  ],
  webServer: {
    command: "pnpm exec vite",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
