import { expect, test } from "@playwright/test";

import { tokens } from "../src/theme/tokens";
import { isMobile, PASSWORD, rgb, signIn, TENANTS } from "./fixtures";

const ITEMS = [
  ["בית", "/home"],
  ["הצעה חדשה", "/new"],
  ["בדיקת הצעה", "/audit"],
  ["מחירון", "/prices"],
  ["תור אישור", "/queue"],
  ["הגדרות", "/prefs"],
] as const;

test("every navigation item opens its screen and is marked current", async ({ page, request }) => {
  await signIn(page, request, TENANTS.classic);
  await page.goto("/home");
  const nav = page.getByRole("navigation", { name: "ניווט" }).or(page.getByRole("complementary", { name: "ניווט" }));
  await expect(nav).toHaveCount(1); // the rail on desktop, the tab bar on mobile, never both
  if (isMobile(page)) await expect(page.locator(".tabbar")).toBeVisible();
  else await expect(page.locator(".rail")).toBeVisible();

  for (const [label, path] of ITEMS) {
    const link = nav.getByRole("link", { name: new RegExp(`^${label}`) });
    await link.click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(link).toHaveAttribute("aria-current", "page");
  }
});

test("the queue badge shows the pending count", async ({ page, request }) => {
  await signIn(page, request, TENANTS.classic);
  await page.goto("/home");
  const visible = page.locator(isMobile(page) ? ".tabbar" : ".rail");
  await expect(visible.getByRole("link", { name: /^תור אישור/ }).locator(".count")).toHaveText("3");
});

test("the rail shows the quota and the plan", async ({ page, request }) => {
  test.skip(isMobile(page), "the rail is hidden on phones");
  await signIn(page, request, TENANTS.classic);
  await page.goto("/home");
  await expect(page.getByTestId("quota-meter")).toContainText("12 מתוך 50");
  await expect(page.getByTestId("quota-meter")).toContainText("ניסיון");
  await expect(page.getByTestId("quota-meter").getByRole("meter")).toHaveAttribute("aria-valuenow", "24");
});

test("logout returns to login, and protected pages then redirect there", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("אימייל").fill(TENANTS.classic);
  await page.getByLabel("סיסמה").fill(PASSWORD);
  await page.getByRole("button", { name: "כניסה" }).click();
  await expect(page).toHaveURL(/\/home$/);

  // The rail's logout on desktop; on phones the rail is hidden, so settings offers it until S24.
  if (isMobile(page)) {
    await page.goto("/prefs");
    await page.getByTestId("logout-prefs").click();
  } else {
    await page.getByTestId("logout").click();
  }
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/queue");
  await expect(page).toHaveURL(/\/login$/);
});

test("an invalid token is dropped and the user goes to login", async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem("konboro:token", "not-a-real-token"));
  await page.goto("/audit");
  await expect(page).toHaveURL(/\/login$/);
  expect(await page.evaluate(() => sessionStorage.getItem("konboro:token"))).toBeNull();
});

test("an unknown path goes home", async ({ page, request }) => {
  await signIn(page, request, TENANTS.classic);
  await page.goto("/no-such-page");
  await expect(page).toHaveURL(/\/home$/);
});

test.describe("dark", () => {
  test.use({ colorScheme: "dark" });

  test("the shell uses the dark tokens", async ({ page, request }) => {
    await signIn(page, request, TENANTS.classic);
    await page.goto("/home");
    const bar = page.locator(isMobile(page) ? ".tabbar" : ".rail");
    await expect(bar).toHaveCSS("background-color", rgb(tokens.dark.colors.surface));
    await expect(page.locator("body")).toHaveCSS("background-color", rgb(tokens.dark.colors.bg));
    await expect(page.locator(".card").first()).toHaveCSS("border-top-color", rgb(tokens.dark.colors.line));
  });
});

test("keyboard only: Tab reaches the navigation and home actions, with a visible focus ring", async ({
  page,
  request,
}) => {
  await signIn(page, request, TENANTS.classic);
  await page.goto("/home");
  // the home actions render after the summary loads; tabbing before that cycles through the navigation only (BUG-021)
  await expect(page.getByText("בדיקת הצעה קיימת").first()).toBeVisible();
  const reached: string[] = [];
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const style = getComputedStyle(el);
      return {
        name: (el.getAttribute("aria-label") ?? el.textContent ?? "").trim(),
        outline: style.outlineStyle,
        width: style.outlineWidth,
      };
    });
    if (!info) continue;
    expect(info.outline, `focus ring on "${info.name}"`).toBe("solid");
    expect(info.width).toBe("2px");
    reached.push(info.name);
  }
  for (const name of ["הצעה חדשה משרטוט", "בדיקת הצעה קיימת"]) expect(reached.join("|")).toContain(name);
  if (!isMobile(page)) expect(reached.join("|")).toContain("מחירון");
});

test("keyboard only: the login form can be filled and sent without a mouse", async ({ page }) => {
  await page.goto("/login");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("אימייל")).toBeFocused();
  await page.keyboard.type(TENANTS.classic);
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("סיסמה")).toBeFocused();
  await page.keyboard.type(PASSWORD);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/home$/);
});
