import { defineConfig } from "@playwright/test";

import base from "../../playwright.config";

/**
 * Prototype-fidelity capture (docs/dev-strategy.md §5): `make fidelity`.
 * Uses the same E2E API and web app as the main suite, plus a static server for prototype/.
 */
export const prototypePort = Number(process.env.KONBORO_PROTOTYPE_PORT ?? 5182);

export default defineConfig({
  ...base,
  testDir: ".",
  testMatch: "capture.ts",
  testIgnore: [],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  projects: [{ name: "fidelity" }],
  webServer: [
    ...(Array.isArray(base.webServer) ? base.webServer : []).map((server) => ({
      ...server,
      cwd: server.cwd ? `../../${server.cwd}` : "../..", // paths in the base config are relative to frontend/
    })),
    {
      command: `python3 serve_prototype.py ${prototypePort} ../../../prototype`,
      url: `http://127.0.0.1:${prototypePort}/konboro-app.html`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});
