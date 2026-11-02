/**
 * A BOM with no drawing (01 §5.8, S14): a spreadsheet goes through the 7 stages to the done step; one whose headers
 * code doesn't know stops on the confirmation step, where the user sets the columns' roles (`bom_column_mapping`,
 * S14 decision 1). The E2E worker's stand-in model maps unknown headers by position: the first column is the item,
 * the second the quantity (backend devtools/fake_llm.py).
 */
import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, TENANTS } from "./fixtures";

test.describe.configure({ mode: "serial", timeout: 60_000 });

function tenant(page: Page): string {
  return isMobile(page) ? TENANTS.bomMobile : TENANTS.bomDesktop;
}

function csv(name: string, body: string) {
  return { name, mimeType: "text/csv", buffer: Buffer.from(body, "utf-8") };
}

test.beforeEach(async ({ page, request }) => {
  await signIn(page, request, tenant(page));
  await page.goto("/new");
});

test("a spreadsheet BOM goes through all 7 stages", async ({ page }) => {
  await page
    .locator("#file-in")
    .setInputFiles(csv("boq.csv", 'תיאור,כמות,לוח\n"מא""ז 1X16",12,לוח ראשי\nמגען 3X25,2,\n'));
  await expect(page.getByRole("listitem").filter({ hasText: "boq.csv" }).getByText("תקין")).toBeVisible();
  await page.getByTestId("start").click();

  const done = page.getByTestId("done");
  await expect(done).toBeVisible({ timeout: 30_000 });
  const grid = done.locator(".sumgrid");
  await expect(grid).toContainText("כתב כמויות");
  await expect(grid).toContainText("בלי שרטוט");
  await expect(grid).toContainText("לוח ראשי");
  await expect(grid).toContainText("0 פענוח · 1 הקשר · 0 דילוג");
  await expect(done.getByRole("combobox", { name: "סוג עמוד 1" })).toHaveValue("bom_table");
  await expect(page.getByTestId("bom-mapping")).toHaveCount(0); // the mapping is the confirmation step's
});

test("a spreadsheet the code can't map waits for the user's columns", async ({ page }) => {
  await page
    .locator("#file-in")
    .setInputFiles(csv("unknown-headers.csv", 'אלפא,בטא,גמא\nמגען 3X25,2,120.50\n"מא""ז 1X16",14,18\n'));
  await page.getByTestId("start").click();

  const confirm = page.getByTestId("confirm-pages");
  await expect(confirm).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("confirm-reasons")).toContainText("העמודות בכתב הכמויות");
  const mapping = page.getByTestId("bom-mapping");
  await expect(mapping.getByRole("region", { name: "עמודות כתב הכמויות" })).toBeVisible();
  const a = mapping.getByRole("combobox", { name: "תפקיד עמודה A" });
  const b = mapping.getByRole("combobox", { name: "תפקיד עמודה B" });
  const c = mapping.getByRole("combobox", { name: "תפקיד עמודה C" });
  await expect(a).toHaveValue("item");
  await expect(b).toHaveValue("quantity");
  await expect(c).toHaveValue("other");
  await expect(mapping.getByRole("row").filter({ hasText: "אלפא" })).toContainText("מגען 3X25");
  await expect(mapping.getByText("הצעה, לבדיקה")).toHaveCount(3);

  // without a quantity column nothing would be read: "אשר והמשך" waits
  await b.selectOption("other");
  await expect(b).toHaveValue("other");
  await expect(page.getByTestId("confirm")).toBeDisabled();
  await expect(page.getByTestId("confirm-note")).toHaveText("בחרו עמודת פריט אחת ועמודת כמות אחת.");

  await b.selectOption("quantity");
  await c.selectOption("price");
  await expect(c).toHaveValue("price");
  await expect(mapping.getByText("נבחר על ידיכם")).toHaveCount(2);
  await expect(page.getByTestId("confirm")).toBeEnabled();
  await page.getByTestId("confirm").click();

  const done = page.getByTestId("done");
  await expect(done).toBeVisible({ timeout: 30_000 });
  await expect(done.locator(".sumgrid")).toContainText("כתב כמויות");
});
