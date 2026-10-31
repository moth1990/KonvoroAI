import { expect, test, type Page } from "@playwright/test";

import { tokens } from "../src/theme/tokens";
import { rgb } from "./fixtures";

async function bodyBackground(page: Page): Promise<string> {
  return page.evaluate(() => getComputedStyle(document.body).backgroundColor);
}

test("the app loads in Hebrew, right to left, at the login screen", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "he");
  await expect(page.getByRole("heading", { name: "כניסה" })).toBeVisible();
});

test("body text is the prototype's 14px / 1.5 in the prototype's body font", async ({ page }) => {
  await page.goto("/login");
  const body = page.locator("body");
  await expect(body).toHaveCSS("font-size", "14px");
  await expect(body).toHaveCSS("line-height", "21px");
  await expect(body).toHaveCSS("font-family", /^"IBM Plex Sans Hebrew"/);
});

test("designators read left to right inside RTL text", async ({ page }) => {
  await page.goto("/login");
  const direction = await page.evaluate(() => {
    const el = document.createElement("span");
    el.className = "des";
    el.textContent = "S203M-C16";
    document.body.append(el);
    const style = getComputedStyle(el);
    return [style.direction, style.unicodeBidi];
  });
  expect(direction).toEqual(["ltr", "isolate"]);
});

test.describe("light", () => {
  test.use({ colorScheme: "light" });

  test("background is the prototype's light --bg", async ({ page }) => {
    await page.goto("/login");
    expect(await bodyBackground(page)).toBe(rgb(tokens.light.colors.bg));
  });

  test('data-theme="dark" forces dark on a light OS', async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
    await expect.poll(() => bodyBackground(page)).toBe(rgb(tokens.dark.colors.bg));
  });
});

test.describe("dark", () => {
  test.use({ colorScheme: "dark" });

  test("background follows the OS to the prototype's dark --bg", async ({ page }) => {
    await page.goto("/login");
    expect(await bodyBackground(page)).toBe(rgb(tokens.dark.colors.bg));
  });

  test('data-theme="light" overrides a dark OS', async ({ page }) => {
    await page.goto("/login");
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
    await expect.poll(() => bodyBackground(page)).toBe(rgb(tokens.light.colors.bg));
  });
});
