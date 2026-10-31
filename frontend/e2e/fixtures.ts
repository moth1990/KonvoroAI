import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Same default as playwright.config.ts. */
export const apiURL = `http://127.0.0.1:${process.env.KONBORO_E2E_API_PORT ?? 8001}`;

/** The E2E tenants that backend/konboro/devtools/e2e.py seeds. Keep the two lists the same. */
export const TENANTS = {
  chat: "chat@e2e.konboro.local", // home_chat on, 12 of 50, sample quotes
  classic: "classic@e2e.konboro.local", // home_chat off, 12 of 50, sample quotes
  near: "near@e2e.konboro.local", // 43 of 50: quota_near
  full: "full@e2e.konboro.local", // 50 of 50: quota_reached
} as const;

export const PASSWORD = "konboro-e2e-password";

/**
 * Signs in through the API and puts the token where the app keeps it, on every page load, so a test starts
 * signed in. Tests of login and logout go through the screen instead.
 */
export async function signIn(page: Page, request: APIRequestContext, email: string): Promise<void> {
  const response = await request.post(`${apiURL}/auth/login`, { data: { email, password: PASSWORD } });
  expect(response.ok()).toBe(true);
  const { access_token: token } = (await response.json()) as { access_token: string };
  await page.addInitScript((t) => sessionStorage.setItem("konboro:token", t), token);
}

/** Is this the phone layout (tab bar instead of the rail)? */
export function isMobile(page: Page): boolean {
  return (page.viewportSize()?.width ?? 1440) <= 860;
}

export function rgb(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}
