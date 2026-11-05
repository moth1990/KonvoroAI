/**
 * The "לא פוענח" layer (13 §4.4, prototype `UNRESOLVED`, `boxesFor`; S26) on the NURSERY-1 fixture: the dashed red
 * boxes and their tabs, the toolbar's count, the strip's dots and the toggle, on the desktop and in the phone's
 * drawing tab; and nothing of it with `unresolved_overlay` off.
 */
import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, TENANTS } from "./fixtures";
import { openNursery } from "./review-helpers";

test.use({ reducedMotion: "reduce" });

const thumb = (page: Page, no: number) =>
  page.getByTestId("page-thumb").and(page.getByLabel(new RegExp(`^עמוד ${no},`)));
const spots = (page: Page) => page.getByTestId("ux");

async function drawing(page: Page) {
  if (isMobile(page)) await page.getByRole("tab", { name: "שרטוט" }).click();
}

async function onPage(page: Page, no: number) {
  await thumb(page, no).click();
  await expect(thumb(page, no)).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("viewer")).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
}

test.describe('the "לא פוענח" layer on the NURSERY-1 fixture', () => {
  test("marks what was not read, page by page, and turns off and on", async ({ page, request }) => {
    await signIn(page, request, TENANTS.review);
    await openNursery(page);
    await drawing(page);

    const toggle = page.getByTestId("ux-toggle");
    await expect(toggle).toHaveText(/לא פוענח\s*12/); // S26 decision 7: RNV, C1–C4, and the prototype's three
    await expect(toggle).toHaveAttribute("aria-pressed", "true"); // on by default, as in the prototype
    for (const no of [4, 5, 8]) await expect(thumb(page, no)).toHaveAccessibleName(/יש בו מה שלא פוענח$/);
    for (const no of [1, 6, 9]) await expect(thumb(page, no)).not.toHaveAccessibleName(/לא פוענח/);
    await expect(page.getByTestId("ux-dot")).toHaveCount(3);

    // page 4, the front view: a symbol the library lacks, and F26–F29 drawn on the front only
    await onPage(page, 4);
    await expect(spots(page)).toHaveCount(2);
    await expect(page.locator("[data-testid=ux][data-kind=unknown_symbol]")).toContainText("סימן לא מזוהה");
    await expect(page.locator("[data-testid=ux][data-kind=front_only]")).toContainText("בחזית בלבד");

    // page 5: RNV, with no model
    await onPage(page, 5);
    await expect(spots(page)).toHaveCount(1);
    const rnv = page.locator("[data-testid=ux][data-kind=partial]");
    await expect(rnv).toContainText("פוענח חלקית");
    await expect(rnv.locator("title").first()).toHaveText("RNV: אין דגם ואין מחיר");

    // page 8: "9 / 5" by RNV's contact, and C1–C4's eight symbols under one tab
    await onPage(page, 8);
    await expect(spots(page)).toHaveCount(9);
    await expect(page.locator("[data-testid=ux][data-kind=orphan_text]")).toContainText("טקסט בלי סימן");
    await expect(page.locator("[data-testid=ux][data-kind=partial]")).toHaveCount(8);
    await expect(page.locator("[data-testid=ux][data-kind=partial][data-tag]")).toHaveCount(1);

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await expect(spots(page)).toHaveCount(0);
    await expect(page.getByTestId("ux-dot")).toHaveCount(0);
    await expect(thumb(page, 8)).not.toHaveAccessibleName(/לא פוענח/);

    await toggle.click();
    await expect(spots(page)).toHaveCount(9);
  });

  test("is not there with the flag off", async ({ page, request }) => {
    await signIn(page, request, TENANTS.s26Off);
    await openNursery(page);
    await drawing(page);
    await expect(page.getByTestId("viewer")).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
    await expect(page.getByRole("toolbar", { name: "כלי השרטוט" }).getByRole("button", { name: "הגדל" })).toBeVisible();
    await expect(page.getByTestId("ux-toggle")).toHaveCount(0);
    await expect(spots(page)).toHaveCount(0);
    await expect(page.getByTestId("ux-dot")).toHaveCount(0);
  });
});
