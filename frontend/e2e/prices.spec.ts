/**
 * The price list (07 §7.2, prototype `vPrices` / `openEditor`; S19): the table with its cards, search and chips, the
 * product editor (suppliers, the preferred one, a fixed price or the rule, history, the drafts that use it), 10 §8's
 * warning on a typed cost and saving anyway, the consumable switch, the bulk brand discount, and the flag off.
 *
 * Each project has its own tenant (saves change it). A test that changes a product puts it back first, through the
 * API, so a retry starts where the first attempt did.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiURL, isMobile, PASSWORD, signIn, TENANTS } from "./fixtures";

test.describe.configure({ mode: "serial", timeout: 60_000 });

function tenant(page: Page): string {
  return isMobile(page) ? TENANTS.pricesMobile : TENANTS.pricesDesktop;
}

interface ApiProduct {
  id: string;
  manufacturer_sku: string | null;
  consumable: boolean;
  suppliers: Record<string, unknown>[];
  sanity: { warning_shown: boolean; warnings: { code: string }[] } | null;
}

async function headers(request: APIRequestContext, email: string) {
  const login = await request.post(`${apiURL}/auth/login`, { data: { email, password: PASSWORD } });
  return { Authorization: `Bearer ${((await login.json()) as { access_token: string }).access_token}` };
}

async function productBySku(request: APIRequestContext, email: string, sku: string): Promise<ApiProduct> {
  const list = (await (
    await request.get(`${apiURL}/price-list/products`, { headers: await headers(request, email) })
  ).json()) as ApiProduct[];
  const found = list.find((p) => p.manufacturer_sku === sku);
  if (!found) throw new Error(`no product ${sku}`);
  return found;
}

/** Puts a product's suppliers back as the demo seed has them (seed.py `PRODUCTS`). */
async function resetSuppliers(
  request: APIRequestContext,
  email: string,
  sku: string,
  rows: { name: string; cost: string; lead: number; preferred: boolean; sku?: string }[],
) {
  const p = await productBySku(request, email, sku);
  const suppliers = rows.map((r) => ({
    supplier_name: r.name,
    supplier_sku: r.sku ?? null,
    unit_cost: r.cost,
    lead_days: r.lead,
    preferred: r.preferred,
    price_date: "2026-10-01",
  }));
  const r = await request.patch(`${apiURL}/price-list/products/${p.id}`, {
    headers: await headers(request, email),
    data: { suppliers },
  });
  expect(r.ok()).toBe(true);
}

const row = (page: Page, text: string) => page.getByTestId("prod").filter({ hasText: text });
const editor = (page: Page) => page.getByRole("dialog");

test.beforeEach(async ({ page, request }) => {
  await signIn(page, request, tenant(page));
});

test("the table, its cards, search and chips", async ({ page }) => {
  await page.goto("/prices");
  await expect(page.getByRole("heading", { name: "מחירון", exact: true })).toBeVisible();
  await expect(page.getByTestId("stat-count")).toHaveText("24");
  await expect(page.getByTestId("stat-nocost")).toHaveText("3"); // the relay, the isolator and the SPD
  const rule = page.locator(".stat").filter({ hasText: "חוק רווח" });
  await expect(rule).toContainText("25%"); // the default rule
  await expect(rule).toContainText("רצפה 15%");

  const s203 = row(page, "S203M-C16");
  await expect(s203).toContainText("ספק א׳");
  await expect(s203).toContainText("+1");
  await expect(s203).toContainText("₪138");
  await expect(s203).toContainText("₪185");
  await expect(s203).toContainText("מחיר קבוע");
  await expect(row(page, "AD22-22DS")).toContainText("חוק רווח 25%"); // the lamp is priced by the rule
  await expect(row(page, "ממסר חוסר מתח")).toContainText("אין ספק");

  const search = page.getByRole("searchbox", { name: 'חיפוש: מוצר, מק"ט, ספק' });
  await search.fill("b-20316"); // a supplier's sku, in another case
  await expect(page.getByTestId("prod")).toHaveCount(1);
  await expect(page.getByTestId("prod")).toContainText("S203M-C16");
  await search.fill("אין כזה");
  await expect(page.getByText("אין מוצרים שמתאימים לחיפוש")).toBeVisible();
  await search.fill("");

  await page.getByTestId("pricef-multi").click();
  await expect(page.getByTestId("pricef-multi")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("prod")).toHaveCount(2); // S203M-C16 and the RCD
  await page.getByTestId("pricef-nocost").click();
  await expect(page.getByTestId("prod")).toHaveCount(3);
  await expect(row(page, "מהדק בדיקה")).toHaveCount(0); // a consumable is not "no cost"
  await page.getByTestId("pricef-all").click();
  await expect(page.getByTestId("prod")).toHaveCount(24);
});

test("edit suppliers: add one, make it preferred, remove one, and see the history", async ({ page, request }) => {
  const email = tenant(page);
  await resetSuppliers(request, email, "XT1C160 TMD80 3P", [
    { name: "ספק ב׳ · מפיץ ABB", cost: "545", lead: 7, preferred: true },
  ]);
  await page.goto("/prices");
  await row(page, "XT1C160 TMD80 3P").click();
  const dialog = editor(page);
  await expect(dialog.getByRole("heading", { name: "עריכת מוצר" })).toBeVisible();
  await expect(dialog.getByTestId("sup-row")).toHaveCount(1);

  await dialog.getByTestId("ed-addsup").click();
  const added = dialog.getByTestId("sup-row").nth(1);
  await added.getByLabel("שם הספק").fill("ספק ו׳");
  await added.getByLabel(/^עלות:/).fill("520");
  await added.getByLabel(/^ימי אספקה:/).fill("3");
  await added.getByRole("radio").check();
  await dialog.getByTestId("ed-save").click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("נשמר", { exact: true })).toBeVisible();

  const xt1 = row(page, "XT1C160 TMD80 3P");
  await expect(xt1).toContainText("ספק ו׳");
  await expect(xt1).toContainText("+1");
  await expect(xt1).toContainText("₪520"); // the preferred supplier's cost; the fixed price stays ₪750
  await expect(xt1).toContainText("₪750");

  await xt1.click();
  await expect(dialog.getByTestId("sup-row")).toHaveCount(2);
  await dialog.getByTestId("sup-row").first().getByTestId("ed-rmsup").click(); // ספק ו׳, preferred, listed first
  await expect(dialog.getByTestId("sup-row")).toHaveCount(1);
  await dialog.getByTestId("ed-save").click();
  await expect(dialog).toBeHidden();
  await expect(xt1).toContainText("₪545");
  await expect(xt1).not.toContainText("+1");

  await xt1.click();
  const history = dialog.getByTestId("ed-history");
  await history.locator("summary").click();
  await expect(history).toContainText("נוסף ספק: ספק ו׳, ₪520");
  await expect(history).toContainText("הוסר ספק: ספק ו׳");
});

test("a typed cost far from the list price warns, and saving anyway is kept", async ({ page, request }) => {
  const email = tenant(page);
  await resetSuppliers(request, email, "S203M-C40", [
    { name: "ספק א׳ · מפיץ ABB", cost: "147", lead: 2, preferred: true },
  ]);
  await page.goto("/prices");
  await row(page, "S203M-C40").click();
  const dialog = editor(page);
  const cost = dialog
    .getByTestId("sup-row")
    .first()
    .getByLabel(/^עלות:/);
  await cost.fill("1470"); // 147 with a slip of the finger
  await cost.blur();
  const warning = dialog.getByTestId("sanity");
  await expect(warning).toContainText("המחיר רחוק ממחירון היצרן (₪228). לבדוק?");
  await expect(warning).toContainText("המחיר הקודם היה ₪147 מ-1.10.2026. לעדכן?");
  await expect(dialog.getByTestId("ed-save")).toBeEnabled();
  await dialog.getByTestId("ed-save").click();
  await expect(dialog).toBeHidden();
  await expect(row(page, "S203M-C40")).toContainText("₪1,470");

  const saved = await productBySku(request, email, "S203M-C40");
  expect(saved.sanity?.warning_shown).toBe(true);
  expect(saved.sanity?.warnings.map((w) => w.code)).toEqual(["far_from_list", "jump_from_previous"]);

  // a cost back in range clears the list warning on blur
  await row(page, "S203M-C40").click();
  await cost.fill("150");
  await cost.blur();
  await expect(warning).not.toContainText("מחירון היצרן");
});

test("a new product on the rule with no supplier is saved and has no cost (S19 decision 1)", async ({ page }) => {
  const name = `ממסר בדיקה ${Date.now()}`;
  await page.goto("/prices");
  await page.getByTestId("prod-new").click();
  const dialog = editor(page);
  await expect(dialog.getByRole("heading", { name: "מוצר חדש" })).toBeVisible();

  await dialog.getByTestId("ed-save").click();
  await expect(page.getByText("חסר שם מוצר")).toBeVisible();
  await dialog.getByLabel("שם המוצר בהצעה").fill(name);
  await dialog.getByLabel("משפחה").selectOption({ label: "ממסר" });
  await dialog.getByTestId("ed-save").click();
  await expect(page.getByText("הזינו מחיר מכירה, או בחרו חוק רווח")).toBeVisible();

  await dialog.getByRole("radio", { name: /לפי חוק הרווח/ }).check();
  await expect(dialog.getByTestId("ed-nocost")).toHaveText("בלי ספק אין עלות, ולכן אין מחיר");
  await dialog.getByTestId("ed-save").click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("המוצר נוסף למחירון")).toBeVisible();

  await page.getByTestId("pricef-nocost").click();
  await expect(row(page, name)).toContainText("אין ספק");
  await expect(row(page, name)).toContainText("הוזן ידנית");
});

test("a cabinet's includes, and the drafts that use a product", async ({ page }) => {
  await page.goto("/prices");
  await row(page, "ארון 1000/800/300").click();
  const dialog = editor(page);
  const includes = dialog.getByRole("group", { name: "כלול בארון" });
  await expect(includes.getByRole("checkbox")).toHaveCount(5);
  await expect(includes.getByRole("checkbox", { name: "פסי צבירה" })).toBeChecked(); // the tenant's default
  await dialog.getByRole("button", { name: "ביטול" }).click();

  await row(page, "SN201M-C10").click();
  await expect(dialog.getByTestId("ed-drafts")).toContainText("בשימוש בטיוטה הפתוחה NURSERY (F1, F2");
  await expect(dialog.getByTestId("ed-drafts")).toContainText("הצעות שנשלחו לא משתנות.");
});

test("the consumable switch", async ({ page, request }) => {
  const email = tenant(page);
  const lamp = await productBySku(request, email, "AD22-22DS");
  if (lamp.consumable) {
    await request.patch(`${apiURL}/price-list/products/${lamp.id}`, {
      headers: await headers(request, email),
      data: { consumable: false },
    });
  }
  await page.goto("/prices");
  const toggle = row(page, "AD22-22DS").getByRole("switch");
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await expect(page.getByText("סומן כחומר עזר: לא שורה נפרדת בהצעה")).toBeVisible();
  await expect(editor(page)).toHaveCount(0); // the switch does not open the editor
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
});

test("the bulk brand discount", async ({ page, request }) => {
  const email = tenant(page);
  await request.delete(`${apiURL}/price-list/brand-discounts/ABB`, { headers: await headers(request, email) });
  await page.goto("/prices");
  await expect(page.getByLabel("מותג")).toHaveValue("ABB");
  const pct = page.getByLabel("הנחה (%)");
  await pct.fill("38");
  await page.getByTestId("brand-save").click();
  await expect(page.getByText("נשמר: ABB, הנחה 38% ממחירון היצרן")).toBeVisible();

  await page.reload();
  await expect(pct).toHaveValue("38");
  await expect(page.getByTestId("brand-priced")).toBeVisible();
  await pct.fill("120");
  await page.getByTestId("brand-save").click();
  await expect(page.getByText("הנחה באחוזים, בין 0 ל-100")).toBeVisible();
  await pct.fill("");
  await page.getByTestId("brand-save").click();
  await expect(page.getByText("הוסרה ההנחה של ABB")).toBeVisible();
});
