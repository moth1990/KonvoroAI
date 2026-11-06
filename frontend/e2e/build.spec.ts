/**
 * The chat quote builder (13 §4.2, S27; prototype `vBuild`, lines 1331–1357), desktop and phone, with the stand-in
 * model (`konboro/devtools/fake_llm.py`, which reads a message the way the prototype's `parseBom` does): the home
 * suggestion opens the builder and its lines appear priced from the demo price list, a second message adds to a
 * line, a correction by message and its undo, a price typed on an unpriced line asks "לעדכן גם במחירון?", the draft
 * opens in the review screen, and with `chat_quote_builder` off there is no builder. Voice is `voice.spec.ts`.
 *
 * Every build adds a quote, so each project has its own tenant.
 */
import { expect, test, type Page } from "@playwright/test";

import { signIn, TENANTS } from "./fixtures";

test.describe.configure({ timeout: 60_000 });

const PROTOTYPE = 'מפסק ראשי 4X63, 12 מא"ז 1X16, פחת 4X40';
const lines = (page: Page) => page.getByTestId("build-line");

async function say(page: Page, text: string) {
  await page.getByTestId("build-input").fill(text);
  await page.getByRole("button", { name: "שלח" }).click();
  await expect(page.getByTestId("build-typing")).toHaveCount(0, { timeout: 20_000 });
}

test.describe("chat_quote_builder on", () => {
  test.beforeEach(async ({ page, request }, info) => {
    await signIn(page, request, info.project.name === "mobile" ? TENANTS.buildMobile : TENANTS.buildDesktop);
  });

  test("the home suggestion opens the builder, and its line appears priced", async ({ page }) => {
    await page.goto("/home");
    await page.getByTestId("home-sugg").filter({ hasText: "בנה הצעה" }).click();
    await expect(page).toHaveURL(/\/build\/drw_/, { timeout: 20_000 });
    await expect(page.getByTestId("build-msgs").locator(".msg.a").last()).toContainText("הוספתי שורה אחת");
    await expect(lines(page)).toHaveCount(1);
    await expect(lines(page).first()).toContainText("S201M");
    await expect(lines(page).first()).toContainText("12");
    await expect(page.getByTestId("build-counts")).toHaveText("שורה אחת");
    await expect(page.getByTestId("build-total")).toContainText("₪");
  });

  test("the prototype's message: three lines, the unpriced one marked, and the draft opens in review", async ({
    page,
  }) => {
    await page.goto("/build");
    await expect(page.getByTestId("build-msgs")).toContainText("תארו את הלוח");
    await say(page, PROTOTYPE);
    await expect(lines(page)).toHaveCount(3);
    await expect(page.getByTestId("build-counts")).toHaveText("3 שורות · 1 בלי מחיר");
    await expect(page.locator("[data-testid=build-line][data-status=red]")).toContainText("4P 63A");
    await expect(page.getByTestId("build-msgs").locator(".msg.a").last()).toContainText("הוספתי 3 שורות");
    await page.getByTestId("build-open").click();
    await expect(page).toHaveURL(/\/review\/quo_/);
    await expect(page.locator(".rv-head")).toContainText("הצעה בצ'אט");
    await expect(page.locator(".rv-head")).toContainText("כתב כמויות");
  });

  test("a second message adds to a line; a correction by message, and its undo", async ({ page }) => {
    await page.goto("/build");
    await say(page, PROTOTYPE);
    const mcb = lines(page).filter({ hasText: "S201M" });
    await expect(mcb).toContainText("12");
    await say(page, 'ועוד 4 מא"ז 1X16');
    await expect(lines(page)).toHaveCount(3);
    await expect(mcb.locator("td.n").first()).toHaveText("16");
    await say(page, "לא 16, 10. ותוריד את הפחת");
    await expect(lines(page)).toHaveCount(2);
    await expect(mcb.locator("td.n").first()).toHaveText("10");
    await expect(page.getByTestId("build-msgs").locator(".msg.a").last()).toContainText("הסרתי");
    await page.getByTestId("build-undo").click();
    await expect(page.getByTestId("toast")).toContainText("השינוי האחרון בוטל");
    await expect(lines(page)).toHaveCount(3);
    await expect(mcb.locator("td.n").first()).toHaveText("16");
  });

  test("a price typed on an unpriced line asks whether to update the price list", async ({ page }) => {
    await page.goto("/build");
    await say(page, PROTOTYPE);
    const price = page.getByTestId("build-price");
    await expect(price).toHaveCount(1);
    await price.fill("850");
    await price.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "לעדכן גם במחירון?" })).toBeVisible();
    await dialog.getByTestId("price-here").click();
    await expect(page.getByTestId("build-counts")).toHaveText("3 שורות");
    await expect(page.locator("[data-testid=build-line]", { hasText: "4P 63A" })).toContainText("₪850");
    await page.getByTestId("undo").click();
    await expect(page.getByTestId("build-price")).toHaveCount(1);
  });
});

test.describe("chat_quote_builder off", () => {
  test("no builder: /build goes home, and no suggestion builds", async ({ page, request }) => {
    await signIn(page, request, TENANTS.buildOff);
    await page.goto("/build");
    await expect(page).toHaveURL(/\/home$/);
    await expect(page.getByTestId("home-sugg").filter({ hasText: "בנה הצעה" })).toHaveCount(0);
    await expect(page.getByTestId("mic-home")).toHaveCount(0); // voice needs the builder (13 §2)
  });
});
