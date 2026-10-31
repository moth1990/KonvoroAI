/**
 * Screenshot baselines for the screens the user accepted in the fidelity review (docs/dev-strategy.md §5):
 * login, home classic with the shell, home chat; light and dark; desktop and mobile projects.
 *
 * They run only inside Playwright's pinned Linux image (e2e/visual/update.sh sets KONBORO_VISUAL), locally and in
 * CI, so fonts and rasterization never differ between the baseline and the check:
 * `make check-screenshots` compares, `make screenshots` rewrites them after an accepted visual change.
 */
import { expect, test, type Page } from "@playwright/test";

import { signIn, TENANTS } from "./fixtures";

test.skip(!process.env.KONBORO_VISUAL, "runs in Playwright's Linux image: `make check-screenshots`");

const SCREENS = [
  { name: "login", path: "/login", tenant: undefined },
  { name: "home-classic", path: "/home", tenant: TENANTS.classic },
  { name: "home-chat", path: "/home", tenant: TENANTS.chat },
] as const;

/** Text that changes with the clock: the weekday, "today, 18:52", the renewal date. */
function volatile(page: Page) {
  return [page.locator(".hero .eyebrow"), page.locator("[data-testid=recent] .muted"), page.locator(".stat .small")];
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(scheme, () => {
    test.use({ colorScheme: scheme });

    for (const screen of SCREENS) {
      test(screen.name, async ({ page, request }) => {
        if (screen.tenant) await signIn(page, request, screen.tenant);
        await page.goto(screen.path);
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
