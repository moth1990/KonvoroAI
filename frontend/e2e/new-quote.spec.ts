/**
 * New quote end to end (01 §4.6, prototype `vNew`): pick → upload → the 7 stages through the real worker → done.
 * Each project has its own upload tenant, and the tests run in order: they share that tenant's quota.
 */
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, SLOW_PROJECT, TENANTS } from "./fixtures";

const NURSERY = fileURLToPath(new URL("../../golden/NURSERY-1/NURSERY-1.pdf", import.meta.url));
const MB = 1024 * 1024;

test.describe.configure({ mode: "serial" });

function tenant(page: Page): string {
  return isMobile(page) ? TENANTS.uploadMobile : TENANTS.uploadDesktop;
}

test.beforeEach(async ({ page, request }) => {
  await signIn(page, request, tenant(page));
  await page.goto("/new");
});

test("a drawing goes through all 7 stages and opens for review", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "הצעה חדשה", level: 1 })).toBeVisible();
  await page.getByLabel("פרויקט / שם הלוח").fill("גן ילדים, לוח ראשי");
  await page.locator("#file-in").setInputFiles(NURSERY);
  const row = page.getByRole("listitem").filter({ hasText: "NURSERY-1.pdf" });
  await expect(row.getByText("תקין")).toBeVisible();
  await expect(page.getByTestId("start-note")).toHaveText("קובץ אחד · ייספר 1 מהמכסה (נותרו 38) רק אם הקליטה מצליחה");

  await page.getByTestId("start").click();
  await expect(page).toHaveURL(/\/new\?drawing=drw_/);
  const done = page.getByTestId("done");
  await expect(done).toBeVisible({ timeout: 30_000 });
  await expect(done.getByRole("heading", { name: "גן ילדים, לוח ראשי" })).toBeVisible();
  await expect(done.getByTestId("thumb")).toHaveCount(9);
  await expect(done.getByRole("img", { name: "עמוד 1" })).toHaveJSProperty("complete", true);
  await expect(done.locator(".sumgrid")).toContainText("9 פענוח · 0 הקשר · 0 דילוג");
  await expect(done).toContainText("נספרה במכסה: 13 מתוך 50"); // counted once, after stage 1
  if (!isMobile(page)) await expect(page.getByTestId("quota-meter")).toContainText("13 מתוך 50");

  await page.reload(); // the URL brings the finished run back
  await expect(page.getByTestId("done")).toBeVisible();
  await page.getByTestId("toreview").click();
  await expect(page).toHaveURL(/\/review\/quo_/);

  await page.goto("/home");
  await expect(page.getByTestId("recent")).toContainText("גן ילדים, לוח ראשי");
});

test("the run step lists the 7 stages and can be cancelled", async ({ page }) => {
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  const run = page.getByTestId("run");
  await expect(run).toBeVisible();
  await expect(run.getByRole("heading")).toContainText("NURSERY-1.pdf");
  await expect(run.locator("li")).toHaveCount(7);
  await expect(page.getByTestId("stage-1")).toHaveAttribute("data-state", /run|done/);
  await expect(run).toContainText("שמרנו לכם מקום אחד במכסה");

  await page.getByTestId("cancelrun").click();
  await expect(page.getByRole("status")).toHaveText("הפענוח בוטל. המקום במכסה שוחרר");
  await expect(page).toHaveURL(/\/new$/);
  // Back to picking, with the files still there (01 §4.6).
  await expect(page.getByRole("listitem").filter({ hasText: "NURSERY-1.pdf" })).toBeVisible();
  await expect(page.getByTestId("start-note")).toContainText("(נותרו 37)"); // nothing new was counted
});

test("a CAD file and an oversized file are rejected before upload", async ({ page }) => {
  await page.locator("#file-in").setInputFiles([
    { name: "MAIN_BOARD.dwg", mimeType: "application/octet-stream", buffer: Buffer.from("AC1027") },
    { name: "scan_site.pdf", mimeType: "application/pdf", buffer: Buffer.alloc(21 * MB) },
  ]);
  const dwg = page.getByRole("listitem").filter({ hasText: "MAIN_BOARD.dwg" });
  const big = page.getByRole("listitem").filter({ hasText: "scan_site.pdf" });
  await expect(dwg.getByText("נדחה")).toBeVisible();
  await expect(dwg).toContainText("ייצאו PDF מתוכנת השרטוט (Plot ל-PDF)");
  await expect(big).toContainText("הקובץ scan_site.pdf גדול מ-20MB");
  await expect(page.getByTestId("start")).toBeDisabled();
  await expect(page.getByTestId("start-note")).toHaveText(
    "2 קבצים חורגים. הסירו אותם או החליפו, כדי שלא יחסר לוח בהצעה.",
  );

  await page.getByRole("button", { name: "הסר את MAIN_BOARD.dwg" }).click();
  await page.getByRole("button", { name: "הסר את scan_site.pdf" }).click();
  await expect(page.getByRole("list", { name: "הקבצים שנבחרו" })).toHaveCount(0);
});

test("the server's own check is shown next to the file", async ({ page }) => {
  // A PDF by name that is really a DWG: the browser can't tell, the server can (01 §4.2).
  await page
    .locator("#file-in")
    .setInputFiles({ name: "plan.pdf", mimeType: "application/pdf", buffer: Buffer.from("AC1027") });
  await page.getByTestId("start").click();
  const row = page.getByRole("listitem").filter({ hasText: "plan.pdf" });
  await expect(row.getByText("נדחה")).toBeVisible();
  await expect(row).toContainText("קבצי DWG ו-DXF עדיין לא נתמכים");
  await expect(page).toHaveURL(/\/new$/);
});

test("a new version does not count against the quota", async ({ page }) => {
  await page.getByTestId("upmode-rev").click();
  await expect(page.getByRole("heading", { name: "גרסה חדשה", level: 1 })).toBeVisible();
  await page.locator("#file-in").setInputFiles(NURSERY);
  await expect(page.getByTestId("start")).toBeDisabled();
  await expect(page.getByTestId("start-note")).toHaveText("בחרו למעלה את ההצעה הקיימת");
  const option = page.locator("#rev-of option", { hasText: "גן ילדים, לוח ראשי · גרסה 1" }).first();
  await page.getByLabel("ההצעה הקיימת").selectOption((await option.getAttribute("value")) ?? "");
  await expect(page.getByTestId("start-note")).toHaveText("קובץ אחד · גרסה חדשה, לא נספרת במכסה");
  await page.getByTestId("start").click();
  const done = page.getByTestId("done");
  await expect(done).toBeVisible({ timeout: 30_000 });
  await expect(done).toContainText("גרסה חדשה של הצעה קיימת. לא נספרה במכסה.");
  if (!isMobile(page)) await expect(page.getByTestId("quota-meter")).toContainText("13 מתוך 50");
});
