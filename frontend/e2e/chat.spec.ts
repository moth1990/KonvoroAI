/**
 * The chat on the review screen (08, 09 §6.7, S25) on the NURSERY-1 fixture, desktop and phone, with the stand-in
 * model (`konboro/devtools/fake_llm.py`): opening it (the header's button and "/", the third tab on the phone), a
 * suggestion answered with line chips, a chip that selects its line, a proposal card that changes nothing until
 * "החל", undo taking it back, "בטל" on a card, "שיחה חדשה", and the chat gone with `chat_layer` off. S25b: a "why"
 * answered from the line's trace with a chip that frames the component, compare with the earlier quote shown by its
 * name, and a brand swap remembered for the factory and undone.
 *
 * Applying changes the quote, so each project has its own tenant, and the tests run in order.
 */
import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, TENANTS } from "./fixtures";
import { lineWith, openNursery } from "./review-helpers";

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

test.describe("S25b: why, compare and remember", () => {
  test.beforeEach(async ({ page, request }, info) => {
    await signIn(page, request, info.project.name === "mobile" ? TENANTS.chatMobile : TENANTS.chatDesktop);
    await openNursery(page);
  });

  test("a why about a line is answered from its trace, and its chip frames the component", async ({ page }) => {
    const row = await lineWith(page, "S203M 3P ‏16A");
    await row.click();
    if (isMobile(page)) await page.keyboard.press("Escape"); // the line's sheet; the line stays selected
    await openChat(page);
    await page.getByTestId("chat-input").fill("למה 3 קטבים?");
    await page.getByTestId("chat-input").press("Enter");
    const answer = chat(page).locator(".msg.a", { hasText: "נקרא מהשרטוט" });
    await expect(answer).toBeVisible();
    await expect(chat(page).getByTestId("show-instance")).toBeVisible();
    await answer.getByTestId("instance-ref").click();
    if (isMobile(page)) await expect(page.getByRole("tab", { name: "שרטוט" })).toHaveAttribute("aria-selected", "true");
    else await expect(chat(page)).toHaveCount(0); // the drawer makes way for the drawing
    await expect(page.locator("[data-testid=hl].sel").first()).toBeVisible();
  });

  test("compare with the earlier quote names it, as only the screen knows it", async ({ page }) => {
    await openChat(page);
    await page.getByTestId("chat-input").fill("תשווה להצעה הקודמת");
    await page.getByTestId("chat-input").press("Enter");
    const answer = chat(page).locator(".msg.a", { hasText: "שורות שונות" });
    await expect(answer).toBeVisible();
    await expect(answer.getByTestId("quote-ref")).toHaveText("NURSERY, הצעה קודמת");
    await expect(answer).toContainText("3 שורות שונות");
    await expect(answer.locator("b.num")).toContainText("₪");
  });

  test("a brand swap remembered for the factory, then undone", async ({ page }) => {
    await openChat(page);
    await chat(page).getByTestId("ask").filter({ hasText: "Schneider" }).click();
    const card = chat(page).getByTestId("proposal").last();
    const choice = card.getByTestId("remember");
    await expect(choice.getByRole("radio")).toHaveText(["רק בהצעה הזו", "לזכור למפעל"]); // NURSERY has no customer
    await expect(card.getByTestId("remember-quote_only")).toHaveAttribute("aria-checked", "true");
    await card.getByTestId("remember-tenant").click();
    await expect(card.getByTestId("remember-tenant")).toHaveAttribute("aria-checked", "true");
    await card.getByTestId("apply").click();
    await expect(card.getByTestId("proposal-state")).toHaveText("הוחל");
    await expect(card.getByTestId("remembered")).toHaveText("נשמר בזיכרון ההתאמות של המפעל");
    await expect(page.getByTestId("toast")).toContainText("נזכור את זה במפעל");
    await page.getByTestId("undo-last").click();
    await expect(card.getByTestId("proposal-state")).toHaveText("בוטל אחרי שהוחל");
  });
});

test("with chat_layer off there is no chat", async ({ page, request }) => {
  await signIn(page, request, TENANTS.chatOff);
  await openNursery(page);
  await expect(page.getByTestId("chat-toggle")).toHaveCount(0);
  await page.keyboard.press("/");
  await expect(chat(page)).toHaveCount(0);
});
