import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Same default as playwright.config.ts. */
export const apiURL = `http://127.0.0.1:${process.env.KONBORO_E2E_API_PORT ?? 8001}`;

/** The E2E tenants that backend/konboro/devtools/e2e.py seeds. Keep the two lists the same. */
export const TENANTS = {
  chat: "chat@e2e.konboro.local", // home_chat on, 12 of 50, sample quotes
  classic: "classic@e2e.konboro.local", // home_chat off, 12 of 50, sample quotes
  near: "near@e2e.konboro.local", // 43 of 50: quota_near
  full: "full@e2e.konboro.local", // 50 of 50: quota_reached
  // Uploads change the quota: one tenant per Playwright project, since the projects run at the same time.
  uploadDesktop: "upload-desktop@e2e.konboro.local",
  uploadMobile: "upload-mobile@e2e.konboro.local",
  // The done-step screenshots: each one the only upload in its tenant, so it is always a fresh decode (BUG-016).
  doneLightDesktop: "done-light-desktop@e2e.konboro.local",
  doneDarkDesktop: "done-dark-desktop@e2e.konboro.local",
  doneLightMobile: "done-light-mobile@e2e.konboro.local",
  doneDarkMobile: "done-dark-mobile@e2e.konboro.local",
  // The NURSERY-1 fixture quote for the review screen (S09); nothing writes to it, so both projects share it.
  review: "review@e2e.konboro.local",
  // BOM uploads (S14), apart from the drawing uploads' quota counts.
  bomDesktop: "bom-desktop@e2e.konboro.local",
  bomMobile: "bom-mobile@e2e.konboro.local",
  // The 26-993 audit fixture (S16): decisions and uploads change it, so one tenant per project; the shots read a
  // third. Each tenant's audit has a fixed id (`AUDITS`).
  auditDesktop: "audit-desktop@e2e.konboro.local",
  auditMobile: "audit-mobile@e2e.konboro.local",
  auditShots: "audit-shots@e2e.konboro.local",
  // The price list (S19): the demo's products and the NURSERY draft. Saves change it, so one tenant per project; the
  // shots read a third.
  pricesDesktop: "prices-desktop@e2e.konboro.local",
  pricesMobile: "prices-mobile@e2e.konboro.local",
  pricesShots: "prices-shots@e2e.konboro.local",
  // The review screen's actions (S23): they change the NURSERY draft, and sending locks it, so one tenant per project.
  reviewDesktop: "review-desktop@e2e.konboro.local",
  reviewMobile: "review-mobile@e2e.konboro.local",
  // The product picker (S23b): the NURSERY draft with a missing line; actions change it, so one tenant per project.
  pickerDesktop: "picker-desktop@e2e.konboro.local",
  pickerMobile: "picker-mobile@e2e.konboro.local",
  // S24. A new factory (no terms accepted): onboarding first, then its first quote shows the banner. Answering changes
  // it, so one tenant per project.
  welcomeDesktop: "welcome-desktop@e2e.konboro.local",
  welcomeMobile: "welcome-mobile@e2e.konboro.local",
  // The settings screen, with the demo price list's 25% default markup; saves change it, so one per project.
  prefsDesktop: "prefs-desktop@e2e.konboro.local",
  prefsMobile: "prefs-mobile@e2e.konboro.local",
  // The prototype's six queue candidates; decisions are final, so one tenant per project.
  queueDesktop: "queue-desktop@e2e.konboro.local",
  queueMobile: "queue-mobile@e2e.konboro.local",
  // The settings and queue screenshots, which change nothing; and a tenant with the three S24 flags off.
  s24Shots: "s24-shots@e2e.konboro.local",
  s24Off: "s24-off@e2e.konboro.local",
  // S25. The chat: applying a proposal changes the NURSERY draft, so one tenant per project; one has `chat_layer` off.
  chatDesktop: "chat-desktop@e2e.konboro.local",
  chatMobile: "chat-mobile@e2e.konboro.local",
  chatOff: "chat-off@e2e.konboro.local",
  chatShots: "chat-shots@e2e.konboro.local", // the fidelity shots: proposals are made, never applied
  // S26. The export sends the draft and saves the template, so one tenant per project; one has both S26 flags off.
  exportDesktop: "export-desktop@e2e.konboro.local",
  exportMobile: "export-mobile@e2e.konboro.local",
  s26Off: "s26-off@e2e.konboro.local",
  // S27. A build adds and counts a quote, so one tenant per project (the chat home on); one with the builder off.
  buildDesktop: "build-desktop@e2e.konboro.local",
  buildMobile: "build-mobile@e2e.konboro.local",
  buildOff: "build-off@e2e.konboro.local",
  buildShots: "build-shots@e2e.konboro.local",
  // S27b. `catalog_lines` on for these only: deciding a waiting line changes the quote, so one tenant per project.
  linesDesktop: "lines-desktop@e2e.konboro.local",
  linesMobile: "lines-mobile@e2e.konboro.local",
  linesShots: "lines-shots@e2e.konboro.local",
  // S28. A new factory's first day: no terms, no price list; its first quote is sent, so one tenant per project.
  dayOneDesktop: "day-one-desktop@e2e.konboro.local",
  dayOneMobile: "day-one-mobile@e2e.konboro.local",
} as const;

/** The fixture audit's id in each audit tenant (`E2eTenant.audit_id` in devtools/e2e.py). */
export const AUDITS = {
  [TENANTS.auditDesktop]: "aud_01JD0E2E000000000000000014",
  [TENANTS.auditMobile]: "aud_01JD0E2E000000000000000015",
  [TENANTS.auditShots]: "aud_01JD0E2E000000000000000016",
} as const;

/** The E2E worker runs this project's stages slowly, so a test can cancel mid-run (devtools/e2e.py). */
export const SLOW_PROJECT = "E2E איטי";

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
