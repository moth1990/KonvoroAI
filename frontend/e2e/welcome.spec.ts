/**
 * A new factory's entry (10 §5.1–5.2, S24; no prototype screen): every page sends it to the two questions and the
 * data terms, an upload waits for the terms, the answers are kept, and its first quote says its prices are kept.
 * With the `onboarding` flag off, nothing waits.
 */
import { fileURLToPath } from "node:url";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiURL, isMobile, PASSWORD, signIn, TENANTS } from "./fixtures";

const NURSERY = fileURLToPath(new URL("../../golden/NURSERY-1/NURSERY-1.pdf", import.meta.url));

// The second test waits on the real pipeline worker (as new-quote.spec.ts does).
test.describe.configure({ mode: "serial", timeout: 180_000 });

function tenant(page: Page): string {
  return isMobile(page) ? TENANTS.welcomeMobile : TENANTS.welcomeDesktop;
}

async function headers(request: APIRequestContext, email: string) {
  const login = await request.post(`${apiURL}/auth/login`, { data: { email, password: PASSWORD } });
  return { Authorization: `Bearer ${((await login.json()) as { access_token: string }).access_token}` };
}

test("a new factory answers two questions and accepts the terms before its first drawing", async ({
  page,
  request,
}, testInfo) => {
  const auth = await headers(request, tenant(page));
  const before = (await (await request.get(`${apiURL}/me`, { headers: auth })).json()) as {
    onboarding_required: boolean;
  };
  // Answering is final: a retry finds the tenant answered, and the next test covers what follows.
  test.skip(testInfo.retry > 0 && !before.onboarding_required, "answered on the first attempt");
  expect(before.onboarding_required).toBe(true);

  const refused = await request.post(`${apiURL}/drawings`, {
    headers: auth,
    multipart: { files: { name: "a.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") } },
  });
  expect(refused.status()).toBe(409);
  expect(((await refused.json()) as { error: { code: string } }).error.code).toBe("data_terms_required");

  await signIn(page, request, tenant(page));
  await page.goto("/new");
  await expect(page).toHaveURL(/\/welcome$/);
  await expect(page.getByRole("heading", { name: "שתי שאלות, ומתחילים", level: 1 })).toBeVisible();

  const markup = page.getByLabel("תוספת על מחיר העלות, באחוזים");
  await expect(markup).toHaveValue("25");
  await expect(page.getByTestId("markup-example")).toHaveText("דוגמה: עלות ₪100 ← מחיר ללקוח ₪125");
  await markup.fill("abc");
  await expect(markup).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByTestId("markup-example")).toHaveText("הזינו אחוז במספרים, עד 500");
  await markup.fill("30");
  await expect(page.getByTestId("markup-example")).toHaveText("דוגמה: עלות ₪100 ← מחיר ללקוח ₪130");

  const breakers = page.getByRole("group", { name: "מא״זים" });
  await breakers.getByRole("button", { name: "האגר" }).click();
  await breakers.getByRole("button", { name: "שניידר" }).click(); // one brand per family: the last one picked
  await expect(breakers.getByRole("button", { name: "שניידר" })).toHaveAttribute("aria-pressed", "true");
  await expect(breakers.getByRole("button", { name: "האגר" })).toHaveAttribute("aria-pressed", "false");
  // RCDs skipped (10 §5.1: "אפשר לדלג")

  const start = page.getByTestId("welcome-start");
  await expect(start).toBeDisabled();
  await page.getByTestId("accept-terms").check();
  await start.click();
  await expect(page).toHaveURL(/\/new$/);
  await expect(page.getByRole("heading", { name: "הצעה חדשה", level: 1 })).toBeVisible();

  const state = (await (await request.get(`${apiURL}/onboarding`, { headers: auth })).json()) as Record<
    string,
    unknown
  >;
  expect(state).toMatchObject({
    required: false,
    markup: "0.3000",
    brands: { circuit_breaker: "Schneider", rcd: null },
  });
  await page.goto("/welcome"); // answered: the page is gone
  await expect(page).toHaveURL(/\/home$/);
});

test("the first quote says its prices are kept", async ({ page, request }) => {
  await signIn(page, request, tenant(page));
  await page.goto("/new");
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
  const done = page.getByTestId("done");
  await expect(done).toBeVisible({ timeout: 75_000 });
  await page.getByTestId("toreview").click();
  await expect(page).toHaveURL(/\/review\/quo_/);
  const banner = page.getByTestId("first-quote");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("זו ההצעה הראשונה שלכם.");
  await expect(banner).toContainText("המחירים שתקלידו יישמרו וישמשו בכל ההצעות הבאות.");
});

test("with the flags off nothing waits, and the settings and queue stay placeholders", async ({ page, request }) => {
  await signIn(page, request, TENANTS.s24Off);
  await page.goto("/home");
  await expect(page).toHaveURL(/\/home$/);
  for (const path of ["/prefs", "/queue"]) {
    await page.goto(path);
    await expect(page.getByText("המסך הזה עוד בבנייה.")).toBeVisible();
  }
  const auth = await headers(request, TENANTS.s24Off);
  for (const path of ["/onboarding", "/knowledge-candidates"]) {
    expect((await request.get(`${apiURL}${path}`, { headers: auth })).status()).toBe(404);
  }
});
