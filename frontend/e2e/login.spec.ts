import { expect, test } from "@playwright/test";

import { PASSWORD, TENANTS } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/login");
});

test("valid credentials sign in and land on home", async ({ page }) => {
  await page.getByLabel("אימייל").fill(TENANTS.classic);
  await page.getByLabel("סיסמה").fill(PASSWORD);
  await page.getByRole("button", { name: "כניסה" }).click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("heading", { name: "שלום" })).toBeVisible();
});

test("a wrong password shows the server's Hebrew error and stays on login", async ({ page }) => {
  await page.getByLabel("אימייל").fill(TENANTS.classic);
  await page.getByLabel("סיסמה").fill("not-the-password");
  await page.getByRole("button", { name: "כניסה" }).click();
  await expect(page.getByRole("alert")).toHaveText("האימייל או הסיסמה לא נכונים");
  await expect(page).toHaveURL(/\/login$/);
});

test("client checks: a bad email, then a short password, each focused", async ({ page }) => {
  const email = page.getByLabel("אימייל");
  const password = page.getByLabel("סיסמה");
  await email.fill("not-an-email");
  await page.getByRole("button", { name: "כניסה" }).click();
  await expect(page.getByRole("alert")).toHaveText("כתובת האימייל לא תקינה");
  await expect(email).toBeFocused();
  await expect(email).toHaveAttribute("aria-invalid", "true");

  await email.fill(TENANTS.classic);
  await password.fill("short");
  await page.getByRole("button", { name: "כניסה" }).click();
  await expect(page.getByRole("alert")).toHaveText("הסיסמה צריכה להיות באורך 8 תווים לפחות");
  await expect(password).toBeFocused();
});

test("the password toggle shows and hides the password", async ({ page }) => {
  const password = page.getByLabel("סיסמה");
  const toggle = page.getByTestId("pw");
  await password.fill("secret-123");
  await expect(password).toHaveAttribute("type", "password");
  await toggle.click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(toggle).toHaveText("הסתר");
  await toggle.click();
  await expect(password).toHaveAttribute("type", "password");
  await expect(toggle).toHaveText("הצג");
});

test("forgot password asks for the email first, then confirms with a toast", async ({ page }) => {
  await page.getByTestId("forgot").click();
  await expect(page.getByRole("alert")).toHaveText("כדי לאפס סיסמה, כתבו קודם את כתובת האימייל");
  await page.getByLabel("אימייל").fill("someone@factory.example");
  await page.getByTestId("forgot").click();
  await expect(page.getByRole("status")).toHaveText("אם הכתובת רשומה אצלנו, נשלח אליה קישור לאיפוס");
});

test("a protected page sends you to login, and back there after signing in", async ({ page }) => {
  await page.goto("/prices");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("אימייל").fill(TENANTS.classic);
  await page.getByLabel("סיסמה").fill(PASSWORD);
  await page.getByRole("button", { name: "כניסה" }).click();
  await expect(page).toHaveURL(/\/prices$/);
  await expect(page.getByRole("heading", { name: "מחירון" })).toBeVisible();
});
