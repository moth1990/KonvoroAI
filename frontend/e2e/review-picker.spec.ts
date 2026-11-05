/**
 * The review screen's product picker (S23b, 09 §6.4, §6.6, §7.4, §7.8, §7.13) on the NURSERY-1 fixture with one
 * missing line, desktop and phone: a current set from the list, the bulk brand discount from a row, a missing line
 * resolved through "מוצר אחר…" and one deleted with "אין כאן רכיב", and a component marked on the drawing. Each is
 * undone, so the tests share the draft; each project has its own tenant.
 */
import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, TENANTS } from "./fixtures";
import { lineWith, openNursery } from "./review-helpers";

test.describe.configure({ mode: "serial", timeout: 60_000 });
test.use({ reducedMotion: "reduce" });

test.beforeEach(async ({ page, request }, info) => {
  await signIn(page, request, info.project.name === "mobile" ? TENANTS.pickerMobile : TENANTS.pickerDesktop);
  await openNursery(page);
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
  if (isMobile(page)) await page.getByRole("dialog").getByRole("button", { name: "סגירה" }).click();
}

async function undoLast(page: Page) {
  await page.getByTestId("undo-last").click();
  await expect(toast(page)).toContainText("בוטל");
}

test("a current chosen from the list matches the line again (09 §7.4)", async ({ page }) => {
  const { detail } = await openLine(page, "S203M 3P ‏20A");
  const current = detail.getByLabel("זרם");
  await expect(current).toHaveValue("20");
  await current.selectOption("16");
  await expect(toast(page)).toContainText("הותאם מחדש: ");
  await expect(toast(page)).toContainText("ABB S203M 3P 16A"); // the catalog's wording
  const after = page.getByTestId("line-detail"); // the row's name is the catalog's wording now
  await expect(after.getByText("נקבע ידנית")).toBeVisible();
  await expect(after.getByText("S203M-C16")).toBeVisible();
  await closeSheet(page);
  await undoLast(page);
  await expect((await lineWith(page, "S203M 3P ‏20A")).getByTestId("price-in")).toBeVisible(); // unpriced again
});

test("the brand discount from a row prices the brand's unpriced lines, yellow (09 §7.13)", async ({ page }) => {
  const { detail } = await openLine(page, "S203M 3P ‏20A");
  const bulk = detail.getByTestId("brand-bulk");
  await expect(bulk).toContainText("כל המוצרים של ABB: מחירון יצרן פחות");
  await bulk.getByRole("textbox").fill("30");
  await bulk.getByTestId("brand-save").click();
  await expect(toast(page)).toContainText("שורה אחת קיבלה מחיר: מחירון ABB פחות 30%");
  await closeSheet(page);
  const row = await lineWith(page, "S203M 3P ‏20A");
  await expect(row.locator(".chip", { hasText: "מחיר לפי הנחת מותג" })).toBeVisible();
  await expect(row).toHaveClass(/\by\b/);
  await undoLast(page);
  await expect((await lineWith(page, "S203M 3P ‏20A")).getByTestId("price-in")).toBeVisible();
});

test("a missing line resolved with מוצר אחר… is an approved line (09 §7.8)", async ({ page }) => {
  const { detail } = await openLine(page, "רכיב שלא זוהה");
  const box = detail.getByTestId("missing");
  await expect(box).toContainText("בשרטוט כתוב ״C20״ ליד סימן שהזיהוי לא סימן");
  await box.getByTestId("other-product").click();
  const picker = page.getByRole("dialog", { name: "בחירת מוצר לשורה" });
  await picker.getByTestId("picker-search").fill("S203M-C16");
  await expect(picker.getByTestId("pick").first()).toContainText("S203M-C16");
  await picker.getByTestId("picker-search").press("Enter");
  await expect(toast(page)).toContainText("נוסף: ");
  await expect(toast(page)).toContainText("S203M");
  // the same line, open: a component now, approved, with the product picked
  const resolved = page.getByTestId("line-detail");
  await expect(resolved).toContainText("S203M-C16");
  await expect(resolved.getByTestId("missing")).toHaveCount(0);
  await closeSheet(page);
  await undoLast(page);
  await expect(await lineWith(page, "רכיב שלא זוהה")).toBeVisible();
});

test("אין כאן רכיב deletes the missing line, and בטל brings it back", async ({ page }) => {
  const { detail } = await openLine(page, "רכיב שלא זוהה");
  await detail.getByTestId("no-component").click();
  await expect(toast(page)).toContainText("השורה נמחקה: אין כאן רכיב");
  await expect(lines(page, "רכיב שלא זוהה")).toHaveCount(0);
  await undoLast(page);
  await expect(await lineWith(page, "רכיב שלא זוהה")).toBeVisible();
});

test("draw mode: a rectangle and a product make a manual line there (09 §6.6)", async ({ page }) => {
  if (isMobile(page)) await page.getByRole("tab", { name: "שרטוט" }).click();
  await page
    .getByTestId("page-thumb")
    .and(page.getByLabel(/^עמוד 7,/))
    .click();
  const viewer = page.getByTestId("viewer");
  await expect(viewer).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
  await expect(page.getByTestId("hl").first()).toBeVisible(); // page 7's boxes draw after the viewer is ready (BUG-096)
  const boxes = await page.getByTestId("hl").count();
  await page.getByTestId("draw").click();
  await expect(page.getByTestId("draw-hint")).toBeVisible();
  const area = await page.getByTestId("draw-layer").boundingBox();
  if (!area) throw new Error("no draw layer");
  const at = { x: area.x + area.width * 0.3, y: area.y + area.height * 0.45 };
  // a click is not a rectangle
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  await page.mouse.up();
  await expect(toast(page)).toContainText("גררו מלבן סביב הרכיב");
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  await page.mouse.move(at.x + 60, at.y + 70, { steps: 4 });
  await page.mouse.up();
  const picker = page.getByRole("dialog", { name: "איזה רכיב סימנתם?" });
  await picker.getByTestId("picker-search").fill("S203M-C16");
  await picker.getByTestId("pick").filter({ hasText: "S203M-C16" }).first().click();
  await expect(toast(page)).toContainText("נוסף ידנית: ");
  await expect(page.getByTestId("draw-hint")).toHaveCount(0); // draw mode ends with the mark
  await expect(page.getByTestId("hl")).toHaveCount(boxes + 1);
  await expect(page.locator("[data-testid=hl].m")).toHaveCount(1);
  if (isMobile(page)) await page.getByRole("tab", { name: "שורות" }).click();
  await expect(await rowWithChip(page, "נוסף ידנית")).toHaveCount(1);
  await undoLast(page);
  await expect(page.locator("[data-testid=hl].m")).toHaveCount(0);
});

test("Esc leaves draw mode (09 §8)", async ({ page }) => {
  test.skip(isMobile(page), "the keyboard is the desktop's");
  await page
    .getByTestId("page-thumb")
    .and(page.getByLabel(/^עמוד 7,/))
    .click();
  await page.getByTestId("draw").click();
  await expect(page.getByTestId("draw-hint")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("draw-hint")).toHaveCount(0);
  await expect(page.getByTestId("draw")).toHaveAttribute("aria-pressed", "false");
});

function lines(page: Page, text: string) {
  return page.getByTestId("line").filter({ has: page.locator(".name", { hasText: text }) });
}

/** The list is virtualized: scroll it until a row with this chip is rendered (like `lineWith`, by chip). */
async function rowWithChip(page: Page, chip: string) {
  await page.getByTestId("lines-scroll").evaluate(async (el, wanted) => {
    const frame = () => new Promise((r) => requestAnimationFrame(() => r(null)));
    const find = () =>
      [...el.querySelectorAll<HTMLElement>("[data-testid=line] .chip")].find((c) => c.textContent?.includes(wanted));
    el.scrollTo(0, 0);
    for (let i = 0; i < 60 && !find(); i++) {
      el.scrollBy(0, el.clientHeight * 0.8);
      await frame();
    }
    find()?.scrollIntoView({ block: "center" });
    await frame();
  }, chip);
  return page.getByTestId("line").filter({ has: page.locator(".chip", { hasText: chip }) });
}
