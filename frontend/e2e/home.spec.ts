import { expect, test } from "@playwright/test";

import { clockAtLatestQuote, signIn, TENANTS } from "./fixtures";

test("home_chat off: the classic home with real data", async ({ page, request }) => {
  await signIn(page, request, TENANTS.classic);
  await page.goto("/home");
  await expect(page.getByRole("heading", { name: "שלום" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "מה בונים היום?" })).toHaveCount(0);
  await expect(page.getByTestId("new-quote")).toHaveAttribute("href", "/new");

  await expect(page.locator(".stat").first()).toContainText("12 / 50");
  await expect(page.locator(".stat").nth(1)).toContainText("—");
  await expect(page.locator(".stat").nth(2)).toContainText("אין עדיין נתונים");

  const recent = page.getByTestId("recent").getByRole("link");
  await expect(recent).toHaveCount(3);
  await expect(page.getByTestId("recent")).toContainText("טיוטה · 5 בלי מחיר");
  await expect(page.getByTestId("recent")).toContainText("נשלח · גרסה 1");

  const waiting = page.getByTestId("waiting");
  await expect(waiting.getByRole("link")).toHaveCount(3);
  await expect(waiting).toContainText("5 מחירים חסרים");
  await expect(waiting).toContainText("3 פריטים בתור האישור");
  await expect(waiting).toContainText("3 השמטות בהצעה 10271");
  await expect(waiting).toContainText("לפחות ₪1,250 בסיכון");

  await page.getByRole("link", { name: /פריטים בתור האישור/ }).click();
  await expect(page).toHaveURL(/\/queue$/);
});

test("a shot after midnight sees the seed's times as the baseline did (BUG-098)", async ({ page, request }) => {
  const token = await signIn(page, request, TENANTS.classic);
  const latest = page.getByTestId("recent").getByRole("link").first().locator(".muted").last();
  // the seed ran just before midnight, the shot just after: the newest quote reads "yesterday"
  const seeded = await clockAtLatestQuote(page, request, token);
  await page.clock.setFixedTime(seeded + 24 * 3_600_000);
  await page.goto("/home");
  await expect(latest).toHaveText("אתמול");
  // the visual shots fix the clock at the latest quote, so it reads "today" whenever they run
  await clockAtLatestQuote(page, request, token);
  await page.reload();
  await expect(latest).toHaveText(/^היום, \d{2}:\d{2}$/);
});

test("home_chat on: the chat home", async ({ page, request }) => {
  await signIn(page, request, TENANTS.chat);
  await page.goto("/home");
  await expect(page.getByRole("heading", { name: "מה בונים היום?" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "שלום" })).toHaveCount(0);
  await expect(page.locator(".hero .eyebrow")).toContainText("38 הצעות נותרו החודש");
  await expect(page.locator(".hero .eyebrow")).toContainText(/^יום /);
  // the builder, a question about the latest quote (S27), an audit, the price list
  await expect(page.getByTestId("home-sugg")).toHaveCount(4);
  await expect(page.getByTestId("recent").getByRole("link")).toHaveCount(3);
  await expect(page.getByTestId("mic-home")).toBeVisible(); // `voice_input` (S27)
});

test("chat home: Enter routes the request; Shift+Enter adds a line", async ({ page, request }) => {
  await signIn(page, request, TENANTS.chat);
  await page.goto("/home");
  const input = page.getByTestId("home-input");
  await input.fill("לוח 3 פאזות");
  await input.press("Shift+Enter");
  await expect(input).toHaveValue("לוח 3 פאזות\n");
  await input.fill("בדוק את הצעה 10271");
  await input.press("Enter");
  await expect(page).toHaveURL(/\/audit$/);
});

test("chat home: a question about the latest quote opens it with the chat, asked (S27)", async ({ page, request }) => {
  await signIn(page, request, TENANTS.chat);
  await page.goto("/home");
  const first = await page.getByTestId("recent").getByRole("link").first().getAttribute("href");
  await page.getByTestId("home-sugg").filter({ hasText: "מה חסר בהצעה של" }).click();
  await expect(page).toHaveURL(first ?? /\/review\//);
  // the conversation is the quote's, shared by both projects' runs: the question is the last one asked
  await expect(page.getByTestId("chat").locator(".msg.u").last()).toContainText("מה חסר בהצעה של");
});

test("chat home: an unclear request gets a question with choices, never an action (S27)", async ({ page, request }) => {
  await signIn(page, request, TENANTS.chat);
  await page.goto("/home");
  const input = page.getByTestId("home-input");
  await input.fill("שלום");
  await input.press("Enter");
  const ask = page.getByTestId("home-ask");
  await expect(ask).toContainText("לא בטוח שהבנתי");
  await expect(page).toHaveURL(/\/home$/);
  await ask.getByTestId("home-choice").filter({ hasText: "הצעה משרטוט" }).click();
  await expect(page).toHaveURL(/\/new$/);
});

test("chat home: a suggestion chip routes too", async ({ page, request }) => {
  await signIn(page, request, TENANTS.chat);
  await page.goto("/home");
  await page.getByTestId("home-sugg").filter({ hasText: "מחירון" }).click();
  await expect(page).toHaveURL(/\/prices$/);
});

test("chat home: the attach button opens a new quote", async ({ page, request }) => {
  await signIn(page, request, TENANTS.chat);
  await page.goto("/home");
  await page.getByRole("link", { name: "צרף שרטוט או קובץ" }).click();
  await expect(page).toHaveURL(/\/new$/);
});

test("quota above 80%: the banner and the amber meter", async ({ page, request }) => {
  await signIn(page, request, TENANTS.near);
  await page.goto("/home");
  await expect(page.getByTestId("quota-banner")).toHaveText("נותרו 7 הצעות החודש");
  await expect(page.locator(".stat .meter").first()).toHaveClass(/warn/);
  await expect(page.getByTestId("new-quote")).toBeEnabled();
  await expect(page.getByTestId("waiting")).toContainText("אין כרגע משהו שמחכה לך");
  await expect(page.getByTestId("recent")).toContainText("עדיין אין הצעות");
});

test("quota at 100%: new quote is disabled and says why", async ({ page, request }) => {
  await signIn(page, request, TENANTS.full);
  await page.goto("/home");
  const banner = page.getByTestId("quota-banner");
  await expect(banner).toContainText("הגעתם למכסת ההצעות של החודש");
  await expect(banner).toContainText("להגדלת החבילה");
  const action = page.getByTestId("new-quote");
  await expect(action).toBeDisabled();
  await expect(action).toHaveAttribute("aria-describedby", "quota-banner");
  // Existing work stays available (01 §4.5).
  await expect(page.getByRole("link", { name: /בדיקת הצעה קיימת/ })).toBeEnabled();
  await page.goto("/new");
  await page
    .locator("#file-in")
    .setInputFiles({ name: "a.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.7") });
  await expect(page.getByTestId("start")).toBeDisabled();
  await expect(page.getByTestId("start-note")).toHaveText("המכסה החודשית מלאה. אפשר להעלות גרסה חדשה של שרטוט קיים");
});

test("the chat builder route exists only with its flag", async ({ page, request }) => {
  await signIn(page, request, TENANTS.chat);
  await page.goto("/build");
  await expect(page.getByRole("heading", { name: "הצעה בצ'אט" })).toBeVisible();
});
