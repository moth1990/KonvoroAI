/**
 * Phase 2's exit (roadmap, dev-strategy §8; 10 §2, §11): a new factory produces a quote on its first day. No terms,
 * no price list, nothing sent: the two questions and the data terms, a drawing through the 7 stages, a price typed
 * on a line ("נשמר במחירון"), and the quote sent and locked. Every step is a screen the factory uses, no setup by API.
 *
 * Sending is final, so each project has its own tenant (`day-one-desktop`, `day-one-mobile`).
 */
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { apiURL, isMobile, PASSWORD, signIn, TENANTS } from "./fixtures";

const NURSERY = fileURLToPath(new URL("../../golden/NURSERY-1/NURSERY-1.pdf", import.meta.url));

// The drawing goes through the real pipeline worker, as new-quote.spec.ts's does.
test.describe.configure({ timeout: 180_000 });

function tenant(page: Page): string {
  return isMobile(page) ? TENANTS.dayOneMobile : TENANTS.dayOneDesktop;
}

test("a new factory sends its first quote on its first day", async ({ page, request }, testInfo) => {
  const login = await request.post(`${apiURL}/auth/login`, { data: { email: tenant(page), password: PASSWORD } });
  const auth = { Authorization: `Bearer ${((await login.json()) as { access_token: string }).access_token}` };
  const quotes = (await (await request.get(`${apiURL}/quotes`, { headers: auth })).json()) as { items: unknown[] };
  // Sending is final: a retry finds the quote sent on the first attempt.
  test.skip(testInfo.retry > 0 && quotes.items.length > 0, "sent on the first attempt");
  expect(quotes.items).toHaveLength(0);
  const prices = (await (await request.get(`${apiURL}/price-list/products`, { headers: auth })).json()) as unknown[];
  expect(prices).toHaveLength(0); // an empty price list (10 §2)

  // 1. The two questions and the terms (10 §5.1), with the suggested markup
  await signIn(page, request, tenant(page));
  await page.goto("/new");
  await expect(page).toHaveURL(/\/welcome$/);
  await page.getByTestId("accept-terms").check();
  await page.getByTestId("welcome-start").click();
  await expect(page).toHaveURL(/\/new$/);

  // 2. The drawing, through the 7 stages
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  await expect(page.getByTestId("done")).toBeVisible({ timeout: 75_000 });
  await page.getByTestId("toreview").click();
  await expect(page).toHaveURL(/\/review\/quo_/);
  await expect(page.getByTestId("first-quote")).toContainText("זו ההצעה הראשונה שלכם.");

  // 3. A price typed on a line goes to the factory's price list (09 §7.13, 10 §6)
  const cell = page.getByTestId("price-in").first();
  await expect(cell).toBeVisible();
  await cell.fill("100");
  await cell.press("Enter");
  await expect(page.getByTestId("toast")).toContainText("נשמר במחירון");
  await expect(page.getByTestId("toast")).toContainText("₪100");
  const after = (await (await request.get(`${apiURL}/price-list/products`, { headers: auth })).json()) as unknown[];
  expect(after).toHaveLength(1);

  // 4. Sent and locked (09 §7.12); the lines still without a price are left out, and the dialog says so
  await page.getByTestId("send").click();
  const dialog = page.getByRole("dialog", { name: /לשלוח את גרסה 1/ });
  await expect(dialog).toContainText("שורות בלי מחיר לא נכללות");
  await dialog.getByTestId("dosend").click();
  await expect(page.getByTestId("locked")).toContainText("גרסה 1 נשלחה ללקוח ונעולה");

  const sent = (await (await request.get(`${apiURL}/quotes`, { headers: auth })).json()) as {
    items: { version_status: string }[];
  };
  expect(sent.items.map((q) => q.version_status)).toEqual(["sent"]);
});
