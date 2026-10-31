import { expect, test, type Page } from "@playwright/test";

import { tokens } from "../src/theme/tokens";

function rgb(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

async function bodyBackground(page: Page): Promise<string> {
  return page.evaluate(() => getComputedStyle(document.body).backgroundColor);
}

test("the app loads in Hebrew, right to left", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "he");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("קונבורו");
  await expect(page.getByRole("list", { name: "טוקנים" }).getByRole("listitem")).toHaveCount(18);
});

test("designators read left to right inside RTL text", async ({ page }) => {
  await page.goto("/");
  const des = page.locator(".des").first();
  await expect(des).toHaveCSS("direction", "ltr");
  await expect(des).toHaveCSS("unicode-bidi", "isolate");
});

test.describe("light", () => {
  test.use({ colorScheme: "light" });

  test("background is the prototype's light --bg", async ({ page }) => {
    await page.goto("/");
    expect(await bodyBackground(page)).toBe(rgb(tokens.light.colors.bg));
  });

  test('data-theme="dark" forces dark on a light OS', async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
    await expect.poll(() => bodyBackground(page)).toBe(rgb(tokens.dark.colors.bg));
  });
});

test.describe("dark", () => {
  test.use({ colorScheme: "dark" });

  test("background follows the OS to the prototype's dark --bg", async ({ page }) => {
    await page.goto("/");
    expect(await bodyBackground(page)).toBe(rgb(tokens.dark.colors.bg));
  });

  test('data-theme="light" overrides a dark OS', async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
    await expect.poll(() => bodyBackground(page)).toBe(rgb(tokens.light.colors.bg));
  });
});
