/**
 * New quote end to end (01 §4.6, prototype `vNew`): pick → upload → the 7 stages through the real worker → done.
 * Each project has its own upload tenant, and the tests run in order: they share that tenant's quota.
 */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, SLOW_PROJECT, TENANTS } from "./fixtures";

const NURSERY = fileURLToPath(new URL("../../golden/NURSERY-1/NURSERY-1.pdf", import.meta.url));
const NEVIS = fileURLToPath(new URL("../../golden/NEVIS-1/NEVIS-1.pdf", import.meta.url));
const MB = 1024 * 1024;

// These tests wait on the real pipeline worker, and since S10 stage 2 really renders, tiles and reads every page.
// On a busy CI runner one run can take most of a minute (BUG-022, BUG-033): each done step gets 75 s, and a test that
// decodes twice (a page kind change runs stages 2–7 again) fits in 180 s.
test.describe.configure({ mode: "serial", timeout: 180_000 });

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
  // the start bar's estimate, from the server's page count (01 §4.6 item 4, `live_run`): by the seed or, once the
  // E2E runs number 20, by their medians
  await expect(page.getByTestId("estimate")).toHaveText(/^9 עמודים · (פחות מדקה|כדקה|כ-\d+ דקות) · כ-\$\d+\.\d\d$/);

  await page.getByTestId("start").click();
  await expect(page).toHaveURL(/\/new\?drawing=drw_/);
  const done = page.getByTestId("done");
  await expect(done).toBeVisible({ timeout: 75_000 });
  // the run's time and cost, and the breakdown by stage (01 §4.6 "סיום")
  await expect(done.getByTestId("done-time")).toContainText(/זמן פענוח\s*\d+:\d\d/);
  await expect(done.getByTestId("done-cost")).toContainText("$0.00");
  await done.getByText("פירוט לפי שלב").click();
  await expect(done.getByTestId("breakdown").locator("tbody tr")).toHaveCount(7);
  await expect(done.getByTestId("breakdown").locator("tbody tr").last()).toContainText("קוד בלבד");
  await expect(done.getByRole("heading", { name: "גן ילדים, לוח ראשי" })).toBeVisible();
  await expect(done.getByTestId("thumb")).toHaveCount(9);
  await expect(done.getByRole("img", { name: "עמוד 1" })).toHaveJSProperty("complete", true);
  // The E2E worker's stand-in model classifies like NURSERY-1's labels (backend devtools/fake_llm.py).
  await expect(done.locator(".sumgrid")).toContainText("5 פענוח · 2 הקשר · 2 דילוג");
  await expect(done).toContainText("כל העמודים סווגו בביטחון גבוה");
  await expect(done).toContainText("נספרה במכסה: 13 מתוך 50"); // counted once, after stage 1
  // stage 7 prices the stand-in's one breaker, which carries no values, and adds its enclosure and labels: nothing
  // has a price in this tenant's empty price list. Stage 6 finds one thing, pricing the rest (prototype line 847)
  await expect(done.locator(".sumgrid")).toContainText("מוצר אחד");
  await expect(done.locator(".sumgrid")).toContainText(/0 עם מחיר · \d+ ממצאים/);
  if (!isMobile(page)) await expect(page.getByTestId("quota-meter")).toContainText("13 מתוך 50");

  await page.reload(); // the URL brings the finished run back
  await expect(page.getByTestId("done")).toBeVisible();
  await page.getByTestId("toreview").click();
  await expect(page).toHaveURL(/\/review\/quo_/);
  // stage 7's lines: the breaker, and the derived enclosure the drawing's modules can't size (07 §7.4)
  await expect(page.getByText("ארון: לא ידוע כמה מודולים").first()).toBeVisible();
  await expect(page.getByText("פריטים נלווים ועבודה").first()).toBeVisible();

  await page.goto("/home");
  await expect(page.getByTestId("recent")).toContainText("גן ילדים, לוח ראשי");
});

test("the run step lists the 7 stages and can be cancelled", async ({ page }) => {
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  const run = page.getByTestId("run");
  await expect(run).toBeVisible();
  await expect(run.getByRole("heading", { level: 2 })).toContainText("NURSERY-1.pdf");
  await expect(run.locator("li")).toHaveCount(7);
  await expect(page.getByTestId("stage-1")).toHaveAttribute("data-state", /run|done/);
  await expect(run).toContainText("שמרנו מקום אחד במכסה");

  await page.getByTestId("cancelrun").click();
  // 01 §4.6: the cancel says what the run cost so far; the stand-in model costs nothing
  await expect(page.getByRole("status")).toHaveText("הפענוח בוטל. המקום במכסה שוחרר. עלות עד כה: \u2066$0.00\u2069");
  await expect(page).toHaveURL(/\/new$/);
  // Back to picking, with the files still there (01 §4.6).
  await expect(page.getByRole("listitem").filter({ hasText: "NURSERY-1.pdf" })).toBeVisible();
  await expect(page.getByTestId("start-note")).toContainText("(נותרו 37)"); // nothing new was counted
});

test("the run step says how stage 2 read the text", async ({ page }) => {
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  const stage2 = page.getByTestId("stage-2");
  await expect(stage2).toHaveAttribute("data-state", "done", { timeout: 60_000 });
  // NURSERY-1 draws its letters as lines: every process page goes through OCR (02 §2.3, prototype line 762)
  await expect(stage2).toContainText(/אין שכבת טקסט · נקראו 5 עמודים מהתמונה · \d+ אריחים/);
  await page.getByTestId("cancelrun").click();
  await expect(page.getByRole("status")).toContainText("הפענוח בוטל. המקום במכסה שוחרר");
});

test("the run step counts the symbols stage 3 found", async ({ page }) => {
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  const stage3 = page.getByTestId("stage-3");
  await expect(stage3).toHaveAttribute("data-state", "done", { timeout: 75_000 });
  // the stand-in model finds a breaker on every tile and is always sure: no disambiguation part (prototype line 763)
  await expect(stage3).toContainText(/\d+ רכיבים/);
  await expect(stage3).not.toContainText("בהכרעת מודל");
  await page.getByTestId("cancelrun").click();
  await expect(page.getByRole("status")).toContainText("הפענוח בוטל. המקום במכסה שוחרר");
});

test("the run step counts the devices stage 4 merged", async ({ page }) => {
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  const stage4 = page.getByTestId("stage-4");
  await expect(stage4).toHaveAttribute("data-state", "done", { timeout: 90_000 });
  // the stand-in tags every breaker "Q1": one device per panel, merged by its tag (04 §5.8, prototype line 764)
  await expect(stage4).toContainText(/איחוד לפי תגים: (מכשיר אחד|\d+ מכשירים) (במוצר אחד|ב-\d+ מוצרים)/);
  await page.getByTestId("cancelrun").click();
  await expect(page.getByRole("status")).toContainText("הפענוח בוטל. המקום במכסה שוחרר");
});

test("the run step counts what stage 5 matched", async ({ page }) => {
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  const stage5 = page.getByTestId("stage-5");
  await expect(stage5).toHaveAttribute("data-state", "done", { timeout: 105_000 });
  // the stand-in's breakers carry no current, so none is matched (05 §5.5; prototype line 765)
  await expect(stage5).toContainText(/0 מותאמים · (אחד בלי דגם|\d+ בלי דגם)/);
  await page.getByTestId("cancelrun").click();
  await expect(page.getByRole("status")).toContainText("הפענוח בוטל. המקום במכסה שוחרר");
});

test("the run step counts what stage 6 found", async ({ page }) => {
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  const stage6 = page.getByTestId("stage-6");
  await expect(stage6).toHaveAttribute("data-state", "done", { timeout: 120_000 });
  await expect(stage6).toContainText(/בדיקה.*(ממצא אחד|\d+ ממצאים|אין ממצאים)/); // prototype line 766
  await page.getByTestId("cancelrun").click();
  await expect(page.getByRole("status")).toContainText("הפענוח בוטל. המקום במכסה שוחרר");
});

// --- the live run step (01 §4.6, `live_run`, S28c) ----------------------------------------------------------------

test("the live run says what it does, how long is left and what it costs", async ({ page }) => {
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  const run = page.getByTestId("run");
  await expect(run).toBeVisible();
  // the header's live sentence names the stage; the three measures; the meter by expected time
  await expect(page.getByTestId("run-sub")).toContainText(/^(קליטת השרטוט|קריאת הטקסט|זיהוי הרכיבים)/);
  await expect(page.getByTestId("run-clock")).toHaveText(/^\d+:\d\d$/);
  await expect(page.getByTestId("run-eta")).toHaveText(/^(צפוי כ-|נותרו כ-|נותרו כמה שניות)/);
  await expect(page.getByTestId("run-cost")).toHaveText("$0.00");
  await expect(run.getByRole("progressbar", { name: "התקדמות הפענוח" })).toBeVisible();
  // every stage has its icon; the plain names (01 §4.6)
  await expect(run.locator("li .sico")).toHaveCount(7);
  await expect(page.getByTestId("stage-2")).toContainText("קריאת הטקסט");
  await expect(page.getByTestId("stage-3")).toContainText("זיהוי הרכיבים");
  await expect(page.getByTestId("run-counters")).toContainText("עמודים");

  await expect(page.getByTestId("stage-3")).toHaveAttribute("data-state", "done", { timeout: 75_000 });
  await expect(page.getByTestId("run-counters")).toContainText("עמודים 9/9");
  if (isMobile(page)) {
    // a phone has no page view and no log (01 §4.6)
    await expect(page.getByTestId("run-view")).toBeHidden();
    await expect(page.getByTestId("run-log")).toBeHidden();
  } else {
    await expect(page.getByTestId("run-view")).toBeVisible();
    await expect(page.getByTestId("run-log")).toContainText("רכיבים");
  }
  await expect(page.getByTestId("stage-3").locator(".st")).toHaveText(/\d+:\d\d/); // its time

  // "הודע לי": the browser's permission is asked, a refusal is said, and the in-app notice stays
  await page.context().clearPermissions();
  await page.getByTestId("runnotify").click();
  await expect(page.getByTestId("runnotify")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("cancelrun").click();
  await expect(page.getByRole("status")).toContainText("עלות עד כה");
});

test("the end of a run is told on another screen", async ({ page }) => {
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  await expect(page.getByTestId("run")).toBeVisible();
  await expect(page.getByTestId("stage-1")).toHaveAttribute("data-state", /run|done/);
  // leave the run's screen, in the app (the rail on a desktop, the tab bar on a phone)
  await page.getByRole("link", { name: "בית" }).filter({ visible: true }).first().click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("status")).toContainText(`הפענוח של ${SLOW_PROJECT} הסתיים`, { timeout: 75_000 });
  await expect(page.getByRole("status")).toContainText("לבדיקה ← הצעה חדשה");
});

test("with live_run off the run step is the classic one", async ({ page, request }) => {
  await signIn(page, request, isMobile(page) ? TENANTS.liveOffMobile : TENANTS.liveOffDesktop);
  await page.goto("/new");
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await expect(page.getByRole("listitem").filter({ hasText: "NURSERY-1.pdf" }).getByText("תקין")).toBeVisible();
  await expect(page.getByTestId("estimate")).toHaveCount(0); // no estimate without the flag
  await page.getByTestId("start").click();
  const run = page.getByTestId("run");
  await expect(run).toBeVisible();
  await expect(run.locator("li .dot")).toHaveCount(7); // numbered dots, not icons
  await expect(run.locator(".sico")).toHaveCount(0);
  await expect(page.getByTestId("run-cost")).toHaveCount(0);
  await expect(run).toContainText("שמרנו לכם מקום אחד במכסה");
  await page.getByTestId("cancelrun").click();
  await expect(page.getByRole("status")).toHaveText("הפענוח בוטל. המקום במכסה שוחרר");
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

  // "נקה הכול" (prototype `clearfiles`, S28's flow coverage) empties the list at once
  await page.locator("#file-in").setInputFiles([
    { name: "a.dwg", mimeType: "application/octet-stream", buffer: Buffer.from("AC1027") },
    { name: "b.dwg", mimeType: "application/octet-stream", buffer: Buffer.from("AC1027") },
  ]);
  await expect(page.getByRole("list", { name: "הקבצים שנבחרו" }).getByRole("listitem")).toHaveCount(2);
  await page.getByRole("button", { name: "נקה הכול" }).click();
  await expect(page.getByRole("list", { name: "הקבצים שנבחרו" })).toHaveCount(0);
});

test("the server's own check is shown next to the file", async ({ page }) => {
  // A PDF by name that is really a DWG: the browser can't tell, the server can (01 §4.2). With `live_run` the server
  // checks on pick, for the start bar's estimate (S28c), so the file is refused before "התחל פענוח".
  await page
    .locator("#file-in")
    .setInputFiles({ name: "plan.pdf", mimeType: "application/pdf", buffer: Buffer.from("AC1027") });
  const row = page.getByRole("listitem").filter({ hasText: "plan.pdf" });
  await expect(row.getByText("נדחה")).toBeVisible();
  await expect(row).toContainText("קבצי DWG ו-DXF עדיין לא נתמכים");
  await expect(page.getByTestId("start")).toBeDisabled();
  await expect(page.getByTestId("estimate")).toHaveCount(0);
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
  await expect(done).toBeVisible({ timeout: 75_000 });
  await expect(done).toContainText("גרסה חדשה של הצעה קיימת. לא נספרה במכסה.");
  if (!isMobile(page)) await expect(page.getByTestId("quota-meter")).toContainText("13 מתוך 50");
});

// --- page kinds (01 §5.6, S08) ------------------------------------------------------------------------------------

test("the pages wait for confirmation when the classifier is unsure", async ({ page }) => {
  // A file name with "unsure" makes the stand-in model doubt page 1; NEVIS-1 hasn't been decoded in this tenant.
  await page
    .locator("#file-in")
    .setInputFiles({ name: "unsure-NEVIS-1.pdf", mimeType: "application/pdf", buffer: await readFile(NEVIS) });
  await page.getByTestId("start").click();

  const confirm = page.getByTestId("confirm-pages");
  await expect(confirm).toBeVisible({ timeout: 30_000 });
  await expect(confirm.getByText("ממתין לאישור")).toBeVisible();
  await expect(page.getByTestId("confirm-reasons")).toContainText("ביטחון נמוך");
  const first = confirm.getByTestId("thumb").first();
  await expect(first).toHaveAttribute("data-unsure", "true");
  await expect(first).toContainText("ביטחון נמוך. בדקו את הסוג");

  await page.getByRole("combobox", { name: "סוג עמוד 1" }).selectOption({ label: "חד-קווי" });
  await expect(page.getByText("סוג העמוד עודכן", { exact: true })).toBeVisible();
  await expect(first).not.toHaveAttribute("data-unsure", "true");
  await expect(first).toContainText("סווג על ידיכם");
  await expect(first.getByText("פענוח")).toBeVisible();
  await expect(page.getByTestId("stage-2")).toHaveCount(0); // nothing past stage 1 while waiting

  await page.getByTestId("confirm").click();
  const done = page.getByTestId("done");
  await expect(done).toBeVisible({ timeout: 75_000 });
  await expect(done.locator(".sumgrid")).toContainText("6 פענוח · 1 הקשר · 2 דילוג");
});

test("a page kind changed on the done step decodes again from stage 2", async ({ page }) => {
  await page.locator("#file-in").setInputFiles(NURSERY); // decoded before in this tenant: reused, not counted
  await page.getByTestId("start").click();
  const done = page.getByTestId("done");
  await expect(done).toBeVisible({ timeout: 75_000 });
  await expect(done).toContainText("אותם קבצים כבר פוענחו. לא נספרה במכסה.");
  await expect(done.getByTestId("thumb").nth(1)).toContainText("כמו בשרטוט שכבר פוענח");

  await page.getByRole("combobox", { name: "סוג עמוד 2" }).selectOption({ label: "תוכנית פיקוד" });
  await expect(page.getByText("סוג העמוד עודכן. הפענוח רץ שוב משלב 2")).toBeVisible();
  await expect(page.getByTestId("done")).toBeVisible({ timeout: 75_000 });
  await expect(page.getByTestId("done").locator(".sumgrid")).toContainText("6 פענוח · 2 הקשר · 1 דילוג");
  await expect(page.getByTestId("done").getByTestId("thumb").nth(1)).toContainText("סווג על ידיכם");
});
