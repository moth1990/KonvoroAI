/**
 * Screenshot baselines for the screens the user accepted in the fidelity review (docs/dev-strategy.md §5):
 * login, home classic with the shell, home chat; light and dark; desktop and mobile projects.
 *
 * They run only inside Playwright's pinned Linux image (e2e/visual/update.sh sets KONBORO_VISUAL), locally and in
 * CI, so fonts and rasterization never differ between the baseline and the check:
 * `make check-screenshots` compares, `make screenshots` rewrites them after an accepted visual change.
 */
import { expect, test, type Page } from "@playwright/test";

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { isMobile, signIn, SLOW_PROJECT, TENANTS } from "./fixtures";

test.skip(!process.env.KONBORO_VISUAL, "runs in Playwright's Linux image: `make check-screenshots`");

/** `ready` is what must be on screen before the shot: "network idle" alone can fire before the app's first
 * API call when the machine is busy (emulated amd64, parallel pipeline runs). */
const SCREENS = [
  { name: "login", path: "/login", tenant: undefined, ready: (p: Page) => p.getByRole("heading", { name: "כניסה" }) },
  {
    name: "home-classic",
    path: "/home",
    tenant: TENANTS.classic,
    ready: (p: Page) => p.getByTestId("waiting").getByRole("link").last(),
  },
  {
    name: "home-chat",
    path: "/home",
    tenant: TENANTS.chat,
    ready: (p: Page) => p.getByTestId("recent").getByRole("link").last(),
  },
] as const;

/** The signed-in user's data has arrived: the rail shows the email (it is in the DOM on phones too). */
async function meLoaded(page: Page) {
  await expect(page.locator(".rail-foot span[title]")).toHaveAttribute("title", /@/, { timeout: 60_000 });
}

const NURSERY = fileURLToPath(new URL("../../golden/NURSERY-1/NURSERY-1.pdf", import.meta.url));

/**
 * Text that changes with the clock (the weekday, "today, 18:52", the renewal date) or with the order the tests
 * run in (the quota counts: uploads in parallel tests move them).
 */
function volatile(page: Page) {
  return [
    page.locator(".hero .eyebrow"),
    page.locator("[data-testid=recent] .muted"),
    page.locator(".stat .small"),
    page.getByTestId("quota-meter"),
    page.getByTestId("start-note"),
    page.getByTestId("counted-note"),
  ];
}

async function startUpload(page: Page, project: string) {
  await page.getByLabel("פרויקט / שם הלוח").fill(project);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
}

/** The done step shows whether pages were reused and the count after the upload, so it gets a tenant of its own
 * per scheme and project: always a fresh decode (BUG-016). The other steps share the project's upload tenant. */
function tenantFor(screen: string, scheme: "light" | "dark", mobile: boolean): string {
  if (screen !== "new-done") return mobile ? TENANTS.uploadMobile : TENANTS.uploadDesktop;
  const done = {
    light: { desktop: TENANTS.doneLightDesktop, mobile: TENANTS.doneLightMobile },
    dark: { desktop: TENANTS.doneDarkDesktop, mobile: TENANTS.doneDarkMobile },
  } as const;
  return done[scheme][mobile ? "mobile" : "desktop"];
}

/** The new-quote steps the user accepted in S05: the setup brings each into the state that was reviewed. */
const NEW_QUOTE = [
  {
    name: "new-pick",
    setup: async (page: Page) => {
      await page.getByLabel("פרויקט / שם הלוח").fill("גן ילדים, לוח ראשי");
      await page.locator("#file-in").setInputFiles([
        { name: "NURSERY-1.pdf", mimeType: "application/pdf", buffer: readFileSync(NURSERY) },
        { name: "MAIN_BOARD.dwg", mimeType: "application/octet-stream", buffer: Buffer.from("AC1027") },
      ]);
      await page.getByLabel("פרויקט / שם הלוח").blur();
      await page.getByTestId("start-note").waitFor();
    },
  },
  {
    name: "new-run",
    setup: async (page: Page) => {
      await startUpload(page, SLOW_PROJECT);
      await page.locator('[data-testid="stage-2"][data-state="run"]').waitFor({ timeout: 90_000 });
      await page.mouse.move(0, 0); // no hover on the cancel button
    },
  },
  {
    name: "new-done",
    setup: async (page: Page) => {
      await startUpload(page, "גן ילדים, לוח ראשי");
      await page.getByTestId("done").waitFor({ timeout: 90_000 });
      await page.waitForFunction(() => [...document.images].every((img) => img.complete && img.naturalWidth > 0));
      await page.mouse.move(0, 0);
    },
  },
] as const;

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} new quote`, () => {
    test.use({ colorScheme: scheme });
    test.setTimeout(120_000); // a whole pipeline run, under amd64 emulation on a Mac

    for (const screen of NEW_QUOTE) {
      test(screen.name, async ({ page, request }) => {
        await signIn(page, request, tenantFor(screen.name, scheme, isMobile(page)));
        await page.goto("/new");
        await meLoaded(page);
        await page.evaluate(() => document.fonts.ready);
        await screen.setup(page);
        await expect(page).toHaveScreenshot(`${screen.name}-${scheme}.png`, {
          animations: "disabled",
          mask: volatile(page),
          maxDiffPixelRatio: 0.002,
        });
      });
    }
  });

  test.describe(scheme, () => {
    test.use({ colorScheme: scheme });

    for (const screen of SCREENS) {
      test(screen.name, async ({ page, request }) => {
        if (screen.tenant) await signIn(page, request, screen.tenant);
        await page.goto(screen.path);
        if (screen.tenant) await meLoaded(page);
        await screen.ready(page).waitFor({ timeout: 60_000 });
        await page.waitForLoadState("networkidle");
        await page.evaluate(() => document.fonts.ready);
        await expect(page).toHaveScreenshot(`${screen.name}-${scheme}.png`, {
          animations: "disabled",
          mask: volatile(page),
          maxDiffPixelRatio: 0.002,
        });
      });
    }
  });
}
