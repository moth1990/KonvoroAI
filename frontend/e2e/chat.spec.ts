/**
 * The chat on the review screen (08, 09 §6.7, S25) on the NURSERY-1 fixture, desktop and phone, with the stand-in
 * model (`konboro/devtools/fake_llm.py`): opening it (the header's button and "/", the third tab on the phone), a
 * suggestion answered with line chips, a chip that selects its line, a proposal card that changes nothing until
 * "החל", undo taking it back, "בטל" on a card, "שיחה חדשה", and the chat gone with `chat_layer` off.
 *
 * Applying changes the quote, so each project has its own tenant, and the tests run in order.
 */
import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, TENANTS } from "./fixtures";
import { openNursery } from "./review-helpers";

test.describe.configure({ mode: "serial", timeout: 60_000 });

const chat = (page: Page) => page.getByTestId("chat");

async function openChat(page: Page) {
  if (isMobile(page)) await page.getByRole("tab", { name: "צ'אט" }).click();
  else await page.getByTestId("chat-toggle").click();
  await expect(chat(page)).toBeVisible();
}

test.describe("chat_layer on", () => {
  test.beforeEach(async ({ page, request }, info) => {
    await signIn(page, request, info.project.name === "mobile" ? TENANTS.chatMobile : TENANTS.chatDesktop);
    await openNursery(page);
  });

  test("opens with the quote's greeting, and / focuses the field on the desktop", async ({ page }) => {
    if (isMobile(page)) {
      await openChat(page);
      await expect(page.getByTestId("lines-scroll")).toBeHidden();
    } else {
      await expect(chat(page)).toHaveCount(0);
      await page.keyboard.press("/");
      await expect(page.getByTestId("chat-input")).toBeFocused();
    }
    await expect(chat(page).locator(".msg.a").first()).toContainText("הפענוח של NURSERY הסתיים");
    await expect(chat(page).getByTestId("ask")).toHaveCount(4);
  });

  test("a suggestion is answered with line chips, and a chip selects its line", async ({ page }) => {
    await openChat(page);
    await chat(page).getByTestId("ask").filter({ hasText: "מה חסר כדי לשלוח?" }).click();
    await expect(chat(page).locator(".msg.u", { hasText: "מה חסר כדי לשלוח?" })).toBeVisible();
    const chips = chat(page).getByTestId("line-ref");
    await expect(chips.first()).toBeVisible();
    await expect(chat(page).locator(".msg.a", { hasText: "מצאתי 5 שורות" })).toBeVisible();
    await chips.first().click();
    if (isMobile(page)) await expect(page.getByRole("dialog").getByTestId("line-detail")).toBeVisible();
    else await expect(page.locator("[data-testid=line][aria-current=true]")).toHaveCount(1);
  });

  test("a proposal changes nothing until החל, and undo takes it back", async ({ page }) => {
    await openChat(page);
    const total = await page.getByTestId("rv-totals").locator("b").textContent();
    await chat(page).getByTestId("ask").filter({ hasText: "Schneider" }).click();
    const card = chat(page).getByTestId("proposal").last();
    await expect(card).toBeVisible();
    await expect(card.getByTestId("proposal-state")).toHaveText("ממתין לאישור");
    await expect(card.locator(".diff > div").first()).toContainText("Schneider");
    await expect(card).toContainText("הסכומים מחושבים במערכת, לא במודל");
    await expect(page.getByTestId("rv-totals").locator("b")).toHaveText(total ?? "");
    await card.getByTestId("apply").click();
    await expect(card.getByTestId("proposal-state")).toHaveText("הוחל");
    await expect(page.getByTestId("toast")).toContainText("השינוי הוחל");
    await page.getByTestId("undo-last").click();
    await expect(page.getByTestId("toast")).toContainText("בוטל");
    await expect(card.getByTestId("proposal-state")).toHaveText("בוטל אחרי שהוחל");
  });

  test("בטל on a card, then a new conversation keeps the old one read only", async ({ page }) => {
    await openChat(page);
    await chat(page).getByTestId("ask").filter({ hasText: "Schneider" }).click();
    const card = chat(page).getByTestId("proposal").last();
    await card.getByTestId("dismiss").click();
    await expect(card.getByTestId("proposal-state")).toHaveText("בוטל");
    await expect(card.getByTestId("apply")).toHaveCount(0);
    await chat(page).getByTestId("newchat").click();
    await expect(chat(page).getByTestId("old-convs")).toContainText("לקריאה בלבד");
    await expect(chat(page).getByTestId("proposal")).toHaveCount(0);
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(isMobile(page) ? 375 : 10_000); // no sideways page scroll on the phone
  });
});

test("with chat_layer off there is no chat", async ({ page, request }) => {
  await signIn(page, request, TENANTS.chatOff);
  await openNursery(page);
  await expect(page.getByTestId("chat-toggle")).toHaveCount(0);
  await page.keyboard.press("/");
  await expect(chat(page)).toHaveCount(0);
});
