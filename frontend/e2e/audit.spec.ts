/**
 * The audit of an existing quote (11 §7–8, prototype `vAudit`; S16): the 26-993 fixture as the pipeline audits it on
 * replay (S16 decision 2), a decision on each difference with undo, the evidence on the drawing, the corrected quote
 * on the review screen, and a new audit uploaded through the stand-in model (S16 decision 4).
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiURL, AUDITS, isMobile, PASSWORD, signIn, SLOW_PROJECT, TENANTS } from "./fixtures";
import { lineWith } from "./review-helpers";

test.describe.configure({ mode: "serial", timeout: 90_000 });

function tenant(page: Page): (typeof TENANTS)["auditDesktop" | "auditMobile"] {
  return isMobile(page) ? TENANTS.auditMobile : TENANTS.auditDesktop;
}

function auditId(page: Page): string {
  return AUDITS[tenant(page)];
}

/** Every difference back to open, so a retry starts where the first attempt did. */
async function reopenAll(request: APIRequestContext, email: string, id: string) {
  const login = await request.post(`${apiURL}/auth/login`, { data: { email, password: PASSWORD } });
  const headers = { Authorization: `Bearer ${((await login.json()) as { access_token: string }).access_token}` };
  const audit = (await (await request.get(`${apiURL}/audits/${id}`, { headers })).json()) as {
    differences: { diff_id: string; status: string }[];
  };
  for (const d of audit.differences.filter((x) => x.status !== "open"))
    await request.patch(`${apiURL}/audits/${id}/differences/${d.diff_id}`, { headers, data: { status: "open" } });
}

function csv(name: string, body: string) {
  return { name, mimeType: "text/csv", buffer: Buffer.from(body, "utf-8") };
}

const row = (page: Page, name: string) =>
  page.getByTestId("diff").filter({ has: page.getByText(name, { exact: true }) });

test.beforeEach(async ({ page, request }) => {
  await signIn(page, request, tenant(page));
});

test("26-993: the headline, the numbers and the rows are the audit's own", async ({ page, request }) => {
  await reopenAll(request, tenant(page), auditId(page));
  await page.goto(`/audit/${auditId(page)}`);

  await expect(page.getByText("MAIN_ELECTRICAL_BOARD.pdf")).toBeVisible();
  await expect(page.getByText("26/993 · 5 עמודים · שרטוט ייצור")).toBeVisible();
  await expect(page.getByText('17 שורות · ₪14,022 לפני מע"מ')).toBeVisible();
  // the pipeline finds the factory's three omissions: QG2 short, TC-G1/TC-G2 and MS1–MS3 missing (BUG-031, S17);
  // the headline counts their units. SG, EMS's line and the terminals are below 0.6 (BUG-036)
  await expect(page.getByTestId("audit-headline")).toHaveText(
    "נמצאו 3 הבדלים: 6 רכיבים חסרים. כסף בסיכון: ₪1,250, ועוד 5 רכיבים בלי מחיר. 6 הבדלים לבדוק.",
  );
  const kpis = page.getByTestId("kpis");
  await expect(kpis.locator(".kpi b")).toHaveText(["13 / 17", "3", "₪1,250+", "0"]);
  await expect(kpis).toContainText("6 יחידות");

  const diffs = page.getByTestId("diffs");
  await expect(diffs.getByTestId("diff")).toHaveCount(3);
  const qg = row(page, "מפסק 4X125A");
  await expect(qg).toHaveAttribute("data-type", "qty_short");
  await expect(qg).toHaveClass(/diff-row/);
  await expect(qg.locator(".des")).toHaveText(["QG1", "QG2"]);
  await expect(qg.getByRole("cell").nth(3)).toHaveText("₪1,250");
  const ct = row(page, "משנה זרם 125/5A");
  await expect(ct.locator(".des")).toHaveText(["MS1", "MS2", "MS3"]);
  await expect(ct.getByRole("cell").nth(3)).toHaveText("אין מחיר דומה");
  const trips = diffs.getByTestId("diff").filter({ hasText: "TC-G1" });
  await expect(trips).toHaveAttribute("data-type", "missing_in_quote");
  await expect(trips.locator(".des")).toHaveText(["TC-G1", "TC-G2"]);

  await expect(page.getByRole("heading", { name: "לבדוק" })).toBeVisible();
  await expect(page.getByTestId("to-check").getByTestId("diff")).toHaveCount(6);
  await expect(page.getByTestId("matched").locator("tbody tr")).toHaveCount(13);
  await expect(page.getByTestId("matched").getByText("מכסה כמה מכשירים")).toHaveCount(2);
  // RTL, and no page-wide horizontal scroll on the phone: the tables scroll in their cards
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("a decision is kept, a rejection needs a reason, and undo takes it back", async ({ page, request }) => {
  await reopenAll(request, tenant(page), auditId(page));
  await page.goto(`/audit/${auditId(page)}`);

  const ct = row(page, "משנה זרם 125/5A");
  await ct.getByRole("button", { name: "נכון, זה הבדל: משנה זרם 125/5A" }).click();
  await expect(ct).toHaveAttribute("data-status", "confirmed");
  await expect(ct.getByTestId("decision")).toHaveText("אושר");
  await expect(page.getByTestId("toast")).toContainText("אושר: משנה זרם 125/5A");

  const qg = row(page, "מפסק 4X125A");
  await qg.getByRole("button", { name: "לא נכון: מפסק 4X125A" }).click();
  const dialog = page.getByRole("dialog", { name: "למה זה לא הבדל?" });
  await expect(dialog.getByRole("button", { name: "שמור" })).toBeDisabled();
  await dialog.getByRole("radio", { name: "טעות של המערכת" }).check();
  await dialog.getByLabel("הערה (לא חובה)").fill("QG2 הוא רזרבה");
  await dialog.getByRole("button", { name: "שמור" }).click();
  await expect(qg).toHaveAttribute("data-status", "rejected");
  await expect(qg.getByTestId("decision")).toHaveText("נדחה: טעות של המערכת");
  await expect(qg).not.toHaveClass(/diff-row/);

  await page.getByTestId("undo").click(); // the toast's "בטל"
  await expect(qg).toHaveAttribute("data-status", "open");
  await expect(page.getByTestId("toast")).toContainText("בוטל: נדחה (טעות של המערכת): מפסק 4X125A");

  await page.reload();
  await expect(row(page, "משנה זרם 125/5A")).toHaveAttribute("data-status", "confirmed");
  await expect(row(page, "מפסק 4X125A")).toHaveAttribute("data-status", "open");
  await row(page, "משנה זרם 125/5A").getByRole("button", { name: "שנה את ההחלטה: משנה זרם 125/5A" }).click();
  await expect(row(page, "משנה זרם 125/5A")).toHaveAttribute("data-status", "open");
});

test("show on drawing: the evidence is boxed on its page", async ({ page }) => {
  await page.goto(`/audit/${auditId(page)}`);
  await row(page, "מפסק 4X125A").getByRole("button", { name: "הצג בשרטוט: מפסק 4X125A" }).click();
  const dialog = page.getByRole("dialog", { name: "מפסק 4X125A" });
  const pane = dialog.getByTestId("evidence-drawing");
  await expect(pane.getByTestId("pageinfo")).toContainText("עמוד 3 מתוך 5");
  await expect(pane.locator(".hl")).toHaveCount(2); // QG1 and QG2
  await expect(pane.locator(".hl.r")).toHaveCount(2);
  await expect(pane.getByTestId("panel-frame")).toHaveCount(0); // no panel veils: only the difference
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("the corrected quote opens on the review screen, made once", async ({ page, request }) => {
  await reopenAll(request, tenant(page), auditId(page));
  await page.goto(`/audit/${auditId(page)}`);
  const ct = row(page, "משנה זרם 125/5A");
  await ct.getByRole("button", { name: "נכון, זה הבדל: משנה זרם 125/5A" }).click();
  await expect(ct).toHaveAttribute("data-status", "confirmed");

  await page.getByTestId("corrected-quote").click();
  await expect(page).toHaveURL(/\/review\/quo_[0-9A-Z]{26}$/);
  const url = page.url();
  await expect(await lineWith(page, "משנה זרם")).toHaveCount(1); // the confirmed omission's suggested line

  await page.goto(`/audit/${auditId(page)}`);
  await expect(page.getByTestId("corrected-quote")).toHaveText("פתח את ההצעה המתוקנת");
  await page.getByTestId("corrected-quote").click();
  await expect(page).toHaveURL(url);
});

test("home's omissions card opens the audit", async ({ page }) => {
  await page.goto("/home");
  await page.getByRole("link", { name: /השמטות בהצעה 10271/ }).click();
  await expect(page).toHaveURL(new RegExp(`/audit/${auditId(page)}$`));
  await expect(page.getByTestId("audit-headline")).toBeVisible();
});

test("a new audit: a drawing and its quote go through 5 steps to the results", async ({ page }) => {
  await page.goto("/audit");
  const start = page.getByTestId("start-audit");
  await expect(start).toBeDisabled();
  await expect(page.getByTestId("start-note")).toHaveText("בחרו את השרטוט");

  await page.locator("#audit-quote").setInputFiles(csv("q.zip", "x"));
  await expect(page.getByText("את ההצעה הקיימת מעלים כקובץ אחד: PDF, תמונה, אקסל או CSV.")).toBeVisible();
  await page.getByRole("button", { name: "הסר את q.zip" }).click();

  // the drawing: a BOM, so stage 4 runs in code; the quote: one contactor short and the shunt trips left out
  await page
    .locator("#audit-drawing")
    .setInputFiles(csv("bom.csv", 'פריט;כמות\r\n"מא""ז 3X16";3\r\nמגען 3X25;2\r\nסליל הפסקה;2\r\n'));
  await page
    .locator("#audit-quote")
    .setInputFiles(
      csv(
        "quote.csv",
        'הצעת מחיר מס\' 20001;;;\r\n;;;\r\nתיאור;כמות;מחיר יחידה;סה"כ\r\n"מא""ז 3X16A";3;185;555\r\nמגען 3X25A;1;180;180\r\n',
      ),
    );
  await expect(page.getByTestId("start-note")).toContainText("ייספר 1 מהמכסה");
  await start.click();

  await expect(page).toHaveURL(/\/audit\/aud_[0-9A-Z]{26}$/, { timeout: 75_000 });
  await expect(page.getByTestId("audit-headline")).toContainText("נמצאו 2 הבדלים");
  await expect(page.getByTestId("diffs").locator('[data-type="qty_short"]')).toHaveCount(1);
  await expect(page.getByTestId("diffs").locator('[data-type="missing_in_quote"]')).toHaveCount(1);
  await expect(page.getByText("quote.csv")).toBeVisible();
});

test("the run step counts the audit's 5 steps", async ({ page }) => {
  // the slow project's stages give the run step time to be seen (devtools/e2e.py)
  await page.goto("/audit");
  await page.getByLabel("פרויקט / שם הלוח").fill(SLOW_PROJECT);
  await page.locator("#audit-drawing").setInputFiles(csv("bom.csv", "פריט;כמות\r\nמגען 3X25;2\r\n"));
  await page.locator("#audit-quote").setInputFiles(csv("quote.csv", "תיאור;כמות\r\nמגען 3X25A;2\r\n"));
  await page.getByTestId("start-audit").click();
  const run = page.getByTestId("run");
  await expect(run).toBeVisible({ timeout: 30_000 });
  await expect(run.locator("li.stage")).toHaveCount(5);
  await expect(run.getByTestId("stage-8")).toContainText("בדיקת ההצעה");
  await expect(run).toContainText(/שלב \d מתוך 5/);
  await page.getByTestId("cancelrun").click();
  await expect(page.getByTestId("start-audit")).toBeVisible();
});

test("quote_audit off: /audit is a placeholder", async ({ page }) => {
  await page.route("**/me", async (route) => {
    const response = await route.fetch();
    const me = (await response.json()) as { flags: Record<string, boolean> };
    await route.fulfill({ response, json: { ...me, flags: { ...me.flags, quote_audit: false } } });
  });
  for (const path of ["/audit", `/audit/${auditId(page)}`]) {
    await page.goto(path);
    await expect(page.getByText("המסך הזה עוד בבנייה.")).toBeVisible();
  }
});
