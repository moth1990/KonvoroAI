/**
 * The settings screen (prototype `vPrefs`, S24): the plan and limits, the default markup, the two brand preferences
 * (S24 decision 2), what the enclosure's price includes, the RCD's 30 mA default, and the flags, which are shown
 * and cannot be changed (S03 decision). Each project has its own tenant; each test puts the settings back first.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiURL, isMobile, PASSWORD, signIn, TENANTS } from "./fixtures";

test.describe.configure({ mode: "serial", timeout: 60_000 });

function tenant(page: Page): string {
  return isMobile(page) ? TENANTS.prefsMobile : TENANTS.prefsDesktop;
}

async function reset(request: APIRequestContext, email: string) {
  const login = await request.post(`${apiURL}/auth/login`, { data: { email, password: PASSWORD } });
  const { access_token: token } = (await login.json()) as { access_token: string };
  const r = await request.patch(`${apiURL}/settings`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      default_markup: "0.25",
      brand_preferences: {},
      attribute_defaults: {},
      enclosure_includes_default: { busbar: true, n: true, pe: true, panels: true, doors: true },
    },
  });
  expect(r.ok()).toBe(true);
}

test.beforeEach(async ({ page, request }) => {
  await reset(request, tenant(page));
  await signIn(page, request, tenant(page));
  await page.goto("/prefs");
  await expect(page.getByRole("heading", { name: "הגדרות", level: 1 })).toBeVisible();
});

test("the plan and its limits", async ({ page }) => {
  await expect(page.getByTestId("prefs-quota")).toHaveText("12 / 50");
  await expect(page.locator(".set-row").filter({ hasText: "עמודים לקובץ" })).toContainText("30");
  await expect(page.locator(".set-row").filter({ hasText: "גודל קובץ" })).toContainText("20MB");
  await expect(page.locator(".sec-head").filter({ hasText: "חבילה ומגבלות" }).locator(".chip")).toHaveText("ניסיון");
});

test("the markup, the brands, the enclosure and the 30 mA default are saved", async ({ page }) => {
  const markup = page.getByLabel("תוספת באחוזים");
  await expect(markup).toHaveValue("25");
  await markup.fill("30");
  await markup.press("Enter");
  await expect(page.getByText("התוספת על העלות עודכנה: 30%. הצעות חדשות וחישוב מחדש ישתמשו בה")).toBeVisible();

  await page.getByLabel('מותג מועדף למא"זים').selectOption("Schneider");
  await page.getByLabel("מותג מועדף למפסקי פחת").selectOption("Hager");
  const pe = page.getByRole("switch", { name: "פס הארקה" });
  await expect(pe).toHaveAttribute("aria-checked", "true");
  await pe.click();
  await expect(pe).toHaveAttribute("aria-checked", "false");
  const rcd = page.getByTestId("rcd30");
  await expect(rcd).toHaveAttribute("aria-checked", "false");
  await rcd.click();
  await expect(rcd).toHaveAttribute("aria-checked", "true");

  await page.reload();
  await expect(page.getByLabel("תוספת באחוזים")).toHaveValue("30");
  await expect(page.getByLabel('מותג מועדף למא"זים')).toHaveValue("Schneider");
  await expect(page.getByLabel("מותג מועדף למפסקי פחת")).toHaveValue("Hager");
  await expect(page.getByRole("switch", { name: "פס הארקה" })).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("rcd30")).toHaveAttribute("aria-checked", "true");
});

test("a markup that is not a percent is not saved", async ({ page }) => {
  const markup = page.getByLabel("תוספת באחוזים");
  await markup.fill("abc");
  await markup.press("Enter");
  await expect(page.getByText("הזינו אחוז במספרים, עד 500")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("תוספת באחוזים")).toHaveValue("25");
});

test("flags are shown and cannot be changed", async ({ page }) => {
  const flags = page.getByTestId("flags");
  const switches = flags.getByRole("switch");
  await expect(switches).toHaveCount(5);
  for (const s of await switches.all()) await expect(s).toBeDisabled();
  await expect(flags.getByRole("switch", { name: "הורדת ההצעה" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("button", { name: "הזמן" })).toBeDisabled();
});
