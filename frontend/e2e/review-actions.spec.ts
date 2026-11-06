/**
 * The review screen's actions (09 §7, S23) on the NURSERY-1 fixture, desktop and phone: approve and move on, undo,
 * a price typed in the row, a price change with "לעדכן גם במחירון?", a cost, a supplier, a finding dismissed with a
 * reason, an alternative, the quantity, a delete, and last, sending (which locks the version) and version 2.
 *
 * The actions change the quote, so each project has its own tenant, and the tests run in order.
 */
import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, TENANTS } from "./fixtures";
import { lines, lineWith, openNursery } from "./review-helpers";

test.describe.configure({ mode: "serial", timeout: 60_000 });

test.beforeEach(async ({ page, request }, info) => {
  await signIn(page, request, info.project.name === "mobile" ? TENANTS.reviewMobile : TENANTS.reviewDesktop);
  await openNursery(page);
});

const toast = (page: Page) => page.getByTestId("toast");

/** Opens a line's detail: in the row on the desktop, in the bottom sheet on the phone (09 §5.2). */
async function openLine(page: Page, text: string) {
  const row = await lineWith(page, text);
  await row.locator(".name").click();
  const detail = isMobile(page) ? page.getByRole("dialog") : row.locator("xpath=following-sibling::div[1]");
  await expect(detail.getByTestId("line-detail")).toBeVisible();
  return { row, detail };
}

async function closeSheet(page: Page) {
  if (isMobile(page)) await page.getByRole("dialog").getByRole("button", { name: "סגירה" }).click();
}

test("approve: green with אושר, on to the next line to check, and בטל takes it back", async ({ page }) => {
  const { detail } = await openLine(page, "ממסר עזר");
  await detail.getByTestId("approve").click();
  await expect(toast(page)).toContainText("אושר: ממסר עזר");
  await closeSheet(page);
  const row = await lineWith(page, "ממסר עזר");
  await expect(row.locator(".chip", { hasText: "אושר" })).toBeVisible();
  await expect(row.locator(".chip", { hasText: "אין מחיר" })).toBeVisible(); // approving does not price it
  if (!isMobile(page)) {
    // 09 §7.2: the next line that needs checking is the one selected now
    await expect(page.locator("[data-testid=line][aria-current=true] .name")).toContainText("מגען 3P");
  }
  await page.getByTestId("undo-last").click();
  await expect(toast(page)).toContainText("בוטל: אושר: ממסר עזר");
  await expect((await lineWith(page, "ממסר עזר")).locator(".chip", { hasText: "אושר" })).toHaveCount(0);
});

test("the keyboard approves with Enter (09 §8)", async ({ page }) => {
  test.skip(isMobile(page), "the keyboard is the desktop's");
  const row = await lineWith(page, "מגען 3P");
  await row.locator(".name").click();
  await page.keyboard.press("Space"); // closes the detail; the line stays selected
  await page.keyboard.press("Enter");
  await expect(toast(page)).toContainText("אושר: מגען 3P");
  await expect((await lineWith(page, "מגען 3P")).locator(".chip", { hasText: "אושר" })).toBeVisible();
  await page.keyboard.press("Control+z");
  await expect(toast(page)).toContainText("בוטל");
});

test("a price typed in the row goes to the price list, and Enter moves to the next line with none", async ({
  page,
}) => {
  const before = await page.getByTestId("rv-totals").textContent();
  const row = await lineWith(page, "S203M 3P ‏20A");
  const cell = row.getByTestId("price-in");
  await cell.fill("210");
  await cell.press("Enter");
  await expect(toast(page)).toContainText('נשמר במחירון: מא"ז ABB S203M 3P ‏20A, ₪210');
  await expect(page.getByTestId("rv-totals")).not.toHaveText(before ?? "");
  const priced = await lineWith(page, "S203M 3P ‏20A");
  await expect(priced.locator(".t")).toContainText("₪840");
  await expect(page.getByTestId("findings")).toContainText("4 שורות בלי מחיר");
  if (!isMobile(page)) await expect(page.locator(":focus")).toHaveAttribute("data-testid", "price-in");
});

test("הצג רק אותן shows the lines with no price, and with שמור למחירון off a price is for this quote only", async ({
  page,
}) => {
  // prototype `f-onlyred` and `savelist` (S28's flow coverage)
  await page.getByTestId("findings").getByTestId("f-onlyred").click();
  await expect(page.getByTestId("filter-red")).toHaveAttribute("aria-pressed", "true");
  for (const row of await lines(page).all()) await expect(row.locator(".chip.bad")).toHaveText("אין מחיר");
  const name = (await lines(page).first().locator(".name").textContent()) ?? "";
  const { detail } = await openLine(page, name);
  const toggle = detail.getByTestId("savelist");
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await closeSheet(page);
  const cell = (await lineWith(page, name)).getByTestId("price-in");
  await cell.fill("55");
  await cell.press("Enter");
  await expect(toast(page)).toContainText("נשמר להצעה הזו בלבד");
  await page.getByTestId("filter-all").click();
  await expect((await lineWith(page, name)).locator(".chip", { hasText: "מחיר להצעה הזו" })).toBeVisible();
});

test("a sale price changed for this quote only, then from the price list's new price", async ({ page }) => {
  const { detail } = await openLine(page, "S203M 3P ‏16A");
  await detail.getByLabel("מחיר מכירה ליחידה").fill("190");
  await detail.getByTestId("editprice").click();
  const dialog = page.getByRole("dialog", { name: "לעדכן גם במחירון?" });
  await expect(dialog).toContainText("הצעות שנשלחו לא משתנות.");
  await dialog.getByTestId("price-here").click();
  await expect(toast(page)).toContainText("המחיר שונה רק בהצעה הזו");
  await closeSheet(page);
  const row = await lineWith(page, "S203M 3P ‏16A");
  await expect(row.locator(".chip", { hasText: "מחיר להצעה הזו" })).toBeVisible();
  await page.getByTestId("undo-last").click();
  await expect(toast(page)).toContainText("בוטל");
  await expect((await lineWith(page, "S203M 3P ‏16A")).locator(".chip", { hasText: "מחיר להצעה הזו" })).toHaveCount(0);
});

test("the price list's new price, taken on request (07 §7.2.3)", async ({ page }) => {
  const row = await lineWith(page, "נורת סימון");
  await expect(row.locator(".chip", { hasText: "מחיר חדש במחירון: ₪22.50" })).toBeVisible();
  const { detail } = await openLine(page, "נורת סימון");
  await detail.getByTestId("takefresh").click();
  await expect(toast(page)).toContainText("המחיר עודכן מהמחירון");
  await closeSheet(page);
  await expect((await lineWith(page, "נורת סימון")).locator(".chip", { hasText: "מחיר חדש" })).toHaveCount(0);
});

test("a supplier for this quote, then made the preferred one", async ({ page }) => {
  const { detail } = await openLine(page, "S203M 3P ‏16A");
  const select = detail.getByTestId("supsel");
  await expect(select).toContainText("מועדף");
  const cheaper = await select.locator("option", { hasText: "₪131" }).getAttribute("value");
  await select.selectOption(cheaper ?? "");
  await expect(toast(page)).toContainText("הספק הוחלף רק בהצעה הזו");
  const again = isMobile(page) ? page.getByRole("dialog") : detail;
  await again.getByTestId("mkpref").click();
  await expect(toast(page)).toContainText("הספק המועדף עודכן במחירון");
});

test("a cost for a product with none, and its margin", async ({ page }) => {
  const { detail } = await openLine(page, "ממסר חוסר מתח");
  await detail.getByLabel("עלות ליחידה").fill("200");
  await detail.getByLabel("ספק").fill("ספק בדיקה");
  await detail.getByTestId("addcost").click();
  await expect(toast(page)).toContainText("העלות נשמרה במחירון");
  const again = isMobile(page)
    ? page.getByRole("dialog")
    : (await lineWith(page, "ממסר חוסר מתח")).locator("xpath=following-sibling::div[1]");
  await expect(again).toContainText("₪140");
  await expect(again).toContainText("41%");
});

test("a finding dismissed with a reason (09 §7.7)", async ({ page }) => {
  const findings = page.getByTestId("findings");
  const finding = findings.getByTestId("finding").filter({ hasText: "F26–F29" });
  await finding.getByTestId("f-ignore").click();
  await finding.getByLabel("סיבת דחייה").selectOption("other");
  const dismiss = finding.getByRole("button", { name: "דחה", exact: true });
  await expect(dismiss).toBeDisabled();
  await finding.getByLabel("למה הממצא לא נכון כאן").fill("שאריות בחזית");
  await dismiss.click();
  await expect(toast(page)).toContainText("הממצא נדחה");
  await expect(findings).not.toContainText("F26–F29");
});

test("an alternative, the quantity and a delete, each undone", async ({ page }) => {
  let { detail } = await openLine(page, "מגען 3P");
  await detail.getByTestId("alt").first().click();
  await expect(toast(page)).toContainText("הוחלף");
  await closeSheet(page);
  await expect(await lineWith(page, "מגען 3P ‏18A")).toBeVisible();
  await page.getByTestId("undo-last").click();
  await expect(await lineWith(page, "מגען 3P ‏16A לפחות")).toBeVisible();

  ({ detail } = await openLine(page, "SN201M 1P+N"));
  await detail.getByRole("button", { name: "הוסף כמות" }).click();
  await expect(toast(page)).toContainText("הכמות עודכנה: 18");
  await closeSheet(page);
  await expect((await lineWith(page, "SN201M 1P+N")).locator(".t")).toContainText("₪2,340");

  ({ detail } = await openLine(page, "ממסר עזר"));
  await detail.getByTestId("del").click();
  await expect(toast(page)).toContainText("השורה נמחקה");
  await expect(page.getByTestId("line").filter({ hasText: "ממסר עזר" })).toHaveCount(0);
  await toast(page).getByTestId("undo").click();
  await expect(await lineWith(page, "ממסר עזר")).toBeVisible();
});

test("send asks first, locks the version, and version 2 opens as a draft (09 §7.12)", async ({ page }) => {
  await page.getByTestId("send").click();
  const dialog = page.getByRole("dialog", { name: /לשלוח את גרסה 1/ });
  await expect(dialog).toContainText("שורות בלי מחיר לא נכללות");
  await expect(dialog.getByTestId("dosend")).toHaveText("שלח בכל זאת");
  await dialog.getByTestId("dosend").click();
  await expect(page.getByTestId("locked")).toContainText("גרסה 1 נשלחה ללקוח ונעולה");
  await expect(page.getByTestId("undo-last")).toBeDisabled(); // nothing before sending is undone (09 §7.11)
  await expect(page.getByTestId("price-in")).toHaveCount(0);
  const { detail } = await openLine(page, "ממסר עזר");
  await expect(detail.getByTestId("approve")).toHaveCount(0);
  await closeSheet(page);
  await page.getByTestId("newver").click();
  await expect(toast(page)).toContainText("נפתחה גרסה 2");
  await expect(page.getByTestId("locked")).toHaveCount(0);
  await expect(page.getByText("גרסה 2 · טיוטה")).toBeVisible();
});
