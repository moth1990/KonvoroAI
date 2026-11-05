/**
 * "הורדת ההצעה" (13 §4.1, prototype `exportModal`; S26) on the NURSERY-1 fixture: the modal's preview and warning,
 * the customer PDF and the internal Excel as downloads, the version selector after sending, and the factory's template
 * on the settings screen ("המסמך ללקוח", S26 decision 1). With `export_doc` off, none of it is there.
 *
 * Sending locks the draft and the settings change the template, so the tests run in order, one tenant per project.
 */
import { readFile } from "node:fs/promises";

import { expect, test, type Download, type Page } from "@playwright/test";

import { isMobile, signIn, TENANTS } from "./fixtures";
import { openNursery } from "./review-helpers";

test.describe.configure({ mode: "serial" });

const tenant = (page: Page) => (isMobile(page) ? TENANTS.exportMobile : TENANTS.exportDesktop);
const modal = (page: Page) => page.getByRole("dialog", { name: "הורדת ההצעה" });
const toast = (page: Page) => page.getByTestId("toast");

async function bytes(download: Download): Promise<Buffer> {
  const path = await download.path();
  return readFile(path);
}

/** A 2×1 PNG, red and blue, as a factory's logo would be. */
const LOGO = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAD0lEQVR4nGM4oaGhEXACAAf/AlkO2sKRAAAAAElFTkSuQmCC",
  "base64",
);

test("the modal previews the customer document and downloads the PDF and the Excel", async ({ page, request }) => {
  await signIn(page, request, tenant(page));
  await openNursery(page);
  await page.getByTestId("export").click();

  const dialog = modal(page);
  await expect(dialog).toContainText("דגל");
  await expect(dialog).toContainText("גרסה 1");
  await expect(dialog.getByTestId("export-version")).toHaveCount(0); // one version: no selector
  const doc = dialog.getByTestId("export-doc");
  await expect(doc).toContainText("הצעת מחיר");
  await expect(doc).toContainText("לוח NURSERY · 26/952");
  await expect(doc).toContainText("טיוטה");
  await expect(dialog.getByTestId("export-row")).toHaveCount(13); // 14 lines, Q0's kit part included in its price
  await expect(doc).toContainText("לתשלום ₪5,515.32");
  await expect(dialog.getByTestId("export-unpriced")).toHaveText("5 שורות בלי מחיר יופיעו במסמך בלי סכום.");
  const relay = dialog.getByTestId("export-row").filter({ hasText: "ממסר עזר" });
  await expect(relay.locator("td").nth(2)).toHaveText(""); // no price, no amount (13 §4.1)

  const [pdf] = await Promise.all([page.waitForEvent("download"), dialog.getByTestId("exp-pdf").click()]);
  expect(pdf.suggestedFilename()).toBe("הצעת מחיר NURSERY גרסה 1.pdf");
  expect((await bytes(pdf)).subarray(0, 5).toString()).toBe("%PDF-");

  const [xlsx] = await Promise.all([page.waitForEvent("download"), dialog.getByTestId("exp-xlsx").click()]);
  expect(xlsx.suggestedFilename()).toBe("הצעה פנימית NURSERY גרסה 1.xlsx");
  expect((await bytes(xlsx)).subarray(0, 2).toString()).toBe("PK"); // an xlsx is a zip

  await dialog.getByRole("button", { name: "סגור" }).click();
  await expect(dialog).toHaveCount(0);
});

test("after sending, the selector exports either version", async ({ page, request }) => {
  await signIn(page, request, tenant(page));
  await openNursery(page);
  await page.getByTestId("send").click();
  await page
    .getByRole("dialog", { name: /לשלוח את גרסה 1/ })
    .getByTestId("dosend")
    .click();
  await expect(page.getByTestId("locked")).toBeVisible();
  await page.getByTestId("newver").click();
  await expect(toast(page)).toContainText("נפתחה גרסה 2");

  await page.getByTestId("export").click();
  const dialog = modal(page);
  const select = dialog.getByTestId("export-version");
  await expect(select).toHaveValue("2");
  await expect(select.locator("option")).toHaveText(["גרסה 2 · טיוטה", "גרסה 1 · נשלחה"]);
  await expect(dialog.getByTestId("export-doc")).toContainText("טיוטה");

  await select.selectOption("1");
  await expect(dialog.getByTestId("export-doc")).not.toContainText("טיוטה"); // the version the customer got
  const [pdf] = await Promise.all([page.waitForEvent("download"), dialog.getByTestId("exp-pdf").click()]);
  expect(pdf.suggestedFilename()).toBe("הצעת מחיר NURSERY גרסה 1.pdf");
});

test('"המסמך ללקוח" saves the factory\'s details, terms and logo', async ({ page, request }) => {
  await signIn(page, request, tenant(page));
  await page.goto("/prefs");
  const section = page.getByTestId("document-settings");
  await expect(section.getByRole("heading", { name: "המסמך ללקוח" })).toBeVisible();
  await expect(section.getByTestId("doc-save")).toBeDisabled();

  await section.getByLabel("שם המפעל").fill('לוחות בדיקה בע"מ');
  await section.getByLabel("ח.פ.").fill("510000001");
  await section.getByLabel("טלפון").fill("03-5550000");
  await section.getByLabel("תנאים").fill("ההצעה בתוקף 30 יום.");
  await section.getByRole("switch", { name: 'הצג מק"ט במסמך' }).click();
  await expect(section).toContainText("יש שינויים שלא נשמרו");
  await section.getByTestId("doc-save").click();
  await expect(toast(page)).toContainText("המסמך ללקוח עודכן");
  await expect(section.getByTestId("doc-save")).toBeDisabled();

  await section.getByTestId("doc-logo-file").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: LOGO });
  await expect(toast(page)).toContainText("הלוגו נשמר");
  await expect(section.getByTestId("doc-logo")).toBeVisible();

  await page.reload();
  await expect(section.getByLabel("שם המפעל")).toHaveValue('לוחות בדיקה בע"מ');
  await expect(section.getByLabel("תנאים")).toHaveValue("ההצעה בתוקף 30 יום.");
  await expect(section.getByRole("switch", { name: 'הצג מק"ט במסמך' })).toHaveAttribute("aria-checked", "true");

  await section.getByRole("button", { name: "הסרה" }).click();
  await expect(toast(page)).toContainText("הלוגו הוסר");
  await expect(section.getByTestId("doc-logo")).toHaveCount(0);
});

test("with export_doc off there is no download and no template section", async ({ page, request }) => {
  await signIn(page, request, TENANTS.s26Off);
  await openNursery(page);
  await expect(page.getByTestId("undo-last")).toBeVisible();
  await expect(page.getByTestId("export")).toHaveCount(0);
  await page.goto("/prefs");
  await expect(page.getByRole("heading", { name: "חשבון" })).toBeVisible();
  await expect(page.getByTestId("document-settings")).toHaveCount(0);
});
