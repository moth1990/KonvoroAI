/** Shared by the review screen's specs (review.spec.ts, drawing.spec.ts). */
import { expect, type Page } from "@playwright/test";

/** From home's recent work to the quote, the way a user gets there. */
export async function openNursery(page: Page) {
  await page.goto("/home");
  await page
    .getByTestId("recent")
    .getByRole("link", { name: /NURSERY/ })
    .click();
  await expect(page).toHaveURL(/\/review\/quo_[0-9A-Z]{26}$/);
  await expect(page.getByRole("heading", { name: "NURSERY" })).toBeVisible();
}

export const lines = (page: Page) => page.getByTestId("line");

/** The list is virtualized: scroll it, a screen at a time, until the line whose name has `text` is rendered. */
export async function lineWith(page: Page, text: string) {
  await page.getByTestId("lines-scroll").evaluate(async (el, wanted) => {
    const frame = () => new Promise((r) => requestAnimationFrame(() => r(null)));
    const find = () =>
      [...el.querySelectorAll<HTMLElement>("[data-testid=line]")].find((row) =>
        row.querySelector(".name")?.textContent?.includes(wanted),
      );
    el.scrollTo(0, 0);
    for (let i = 0; i < 60 && !find(); i++) {
      el.scrollBy(0, el.clientHeight * 0.8);
      await frame();
    }
    find()?.scrollIntoView({ block: "center" });
    await frame();
    await frame();
  }, text);
  return lines(page).filter({ has: page.locator(".name", { hasText: text }) });
}
