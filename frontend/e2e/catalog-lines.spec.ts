/**
 * Quote lines from the catalog (S27b, `catalog_lines`; 07 §7.1, 09 §6.4, §7.12, §7.16), desktop and phone, on a
 * spreadsheet BOM: "3X16A" and "3X16A C 10kA" are one product (S203M-C16), so one line of 5; "3X13A" is no product, so
 * it waits for a decision with its nearest products and no price, and the quote can't be sent. A nearest product is
 * chosen and undone, then "מוצר חדש" makes the 13A in the app's wording. One tenant per project: the tests share its
 * quote, in order.
 */
import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, TENANTS } from "./fixtures";
import { lineWith } from "./review-helpers";

test.describe.configure({ mode: "serial", timeout: 90_000 });
test.use({ reducedMotion: "reduce" });

const BOQ = 'תיאור,כמות\n"מא""ז 3X16A",2\n"מא""ז 3X16A C 10kA",3\n"מא""ז 3X13A",1\n';
let reviewUrl = "";

test.beforeEach(async ({ page, request }) => {
  await signIn(page, request, isMobile(page) ? TENANTS.linesMobile : TENANTS.linesDesktop);
  if (reviewUrl) await page.goto(reviewUrl);
});

const toast = (page: Page) => page.getByTestId("toast");

async function openLine(page: Page, text: string) {
  const row = await lineWith(page, text);
  await row.locator(".name").click();
  const detail = isMobile(page) ? page.getByRole("dialog") : row.locator("xpath=following-sibling::div[1]");
  await expect(detail.getByTestId("line-detail")).toBeVisible();
  return { row, detail };
}

async function closeSheet(page: Page) {
  // on the phone, a sheet whose line is gone (it joined another) closes by itself
  const close = page.getByRole("dialog").getByRole("button", { name: "סגירה" });
  if (isMobile(page) && (await close.isVisible())) await close.click();
}

test("one line per product, and a product not in the catalog waits for a decision", async ({ page }) => {
  await page.goto("/new");
  await page
    .locator("#file-in")
    .setInputFiles({ name: "lines.csv", mimeType: "text/csv", buffer: Buffer.from(BOQ, "utf-8") });
  await page.getByTestId("start").click();
  await expect(page.getByTestId("done")).toBeVisible({ timeout: 45_000 });
  await page.getByTestId("toreview").click();
  await expect(page).toHaveURL(/\/review\/quo_/);
  reviewUrl = page.url();

  const merged = await lineWith(page, "S203M 3P 16A");
  await expect(merged).toHaveCount(1);
  await expect(merged).toContainText("5");
  const waiting = await lineWith(page, "13A");
  await expect(waiting).toContainText("מוצר חדש בשרטוט");
  const { detail } = await openLine(page, "13A");
  const box = detail.getByTestId("waiting");
  await expect(box).toContainText("אין בקטלוג מוצר עם הערכים האלה");
  await expect(box.getByTestId("nearest").first()).toBeVisible();
  await expect(box).toContainText("במקום 13A");
  await expect(detail.getByTestId("approve")).toHaveCount(0); // a waiting line is decided, not approved
  await closeSheet(page);

  await page.getByTestId("send").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByTestId("send-pending")).toContainText("מוצר חדש אחד בשרטוט");
  await expect(dialog.getByTestId("dosend")).toBeDisabled();
  await dialog.getByRole("button", { name: "חזרה להצעה" }).click();
});

test("a nearest product joins its line, and undo brings the waiting line back", async ({ page }) => {
  const { detail } = await openLine(page, "13A");
  const near = detail.getByTestId("waiting").locator(".alt").filter({ hasText: "S203M 3P 16A עקומה C" });
  await near.getByTestId("nearest").click();
  await expect(toast(page)).toContainText("נבחר");
  await closeSheet(page);
  await expect(await lineWith(page, "S203M 3P 16A")).toContainText("6");
  await expect(page.getByTestId("line").filter({ hasText: "מוצר חדש בשרטוט" })).toHaveCount(0);

  await page.getByTestId("undo-last").click();
  await expect(toast(page)).toContainText("בוטל");
  await expect(await lineWith(page, "13A")).toContainText("מוצר חדש בשרטוט");
});

test('"מוצר חדש" makes the product in the app\'s wording (09 §7.16)', async ({ page }) => {
  const { detail } = await openLine(page, "13A");
  await detail.getByTestId("new-product").click();
  const form = page.getByRole("dialog").filter({ has: page.getByRole("heading", { name: "מוצר חדש" }) });
  await expect(form.getByTestId("np-current_a")).toHaveValue("13");
  await expect(form.getByTestId("np-save")).toBeDisabled(); // brand and model first
  await form.getByTestId("np-brand").fill("ABB");
  await form.getByTestId("np-model").fill("S203M");
  await form.getByTestId("np-curve").fill("C");
  await expect(form).toContainText("חסר: כושר ניתוק"); // the family's required values, from its schema
  await form.getByTestId("np-breaking_capacity_ka").fill("10");
  await form.getByTestId("np-sku").fill("S203M-C13");
  await expect(form.getByTestId("new-product-name")).toContainText(
    'מפסק זרם אוטומטי (מא"ז) ABB S203M 3P 13A עקומה C 10kA',
  );
  await form.getByTestId("np-save").click();
  await expect(toast(page)).toContainText("נבחר");
  await closeSheet(page);
  const made = await lineWith(page, "ABB S203M 3P 13A");
  await expect(made).toHaveCount(1);
  await expect(page.getByTestId("line").filter({ hasText: "מוצר חדש בשרטוט" })).toHaveCount(0);
  await page.getByTestId("send").click();
  await expect(page.getByRole("dialog").getByTestId("send-pending")).toHaveCount(0);
  await expect(page.getByRole("dialog").getByTestId("dosend")).toBeEnabled();
});
