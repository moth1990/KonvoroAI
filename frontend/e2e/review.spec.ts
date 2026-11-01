/**
 * The review screen, S09 part (09 §5–6.4, §8): the NURSERY-1 fixture quote, filters, line detail, keyboard and
 * the phone's bottom sheet. The drawing pane (S11) is in drawing.spec.ts. States the fixture lacks, and a 150-line quote, come from a mocked API answer.
 */
import { expect, test, type Page } from "@playwright/test";

import type { Quote } from "../src/api/client";
import { line, panel, quote } from "../src/screens/review/fixtures";
import { isMobile, signIn, TENANTS } from "./fixtures";
import { lines, lineWith, openNursery } from "./review-helpers";

/** Scrolls the list to its end, frame by frame, as a finger would; returns how long it took. */
async function scrollToEnd(page: Page): Promise<number> {
  return page.getByTestId("lines-scroll").evaluate(async (el) => {
    const t0 = performance.now();
    for (let i = 0; i < 400 && el.scrollTop + el.clientHeight < el.scrollHeight - 1; i++) {
      el.scrollBy(0, el.clientHeight * 0.8);
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    }
    return performance.now() - t0;
  });
}

test.describe("the NURSERY-1 fixture", () => {
  test.beforeEach(async ({ page, request }) => {
    await signIn(page, request, TENANTS.review);
  });

  test("header, totals and progress come from the server", async ({ page }) => {
    await openNursery(page);
    await expect(page.getByText("26/952 · שרטוט ייצור · גרסה 1 · טיוטה")).toBeVisible();
    const totals = page.getByTestId("rv-totals");
    await expect(totals).toContainText("₪4,674");
    await expect(totals).toContainText("רווח 28%");
    await expect(totals).toContainText("5 חסרים");
    await expect(page.getByTestId("progress")).toContainText("9 מתוך 14 שורות מוכנות");
    await expect(page.getByRole("progressbar", { name: "שורות מוכנות" })).toHaveAttribute("aria-valuenow", "9");
    await expect(page.getByText("כיסוי מחירון 62%")).toBeVisible();
    const foot = page.getByTestId("lines-foot");
    await expect(foot).toContainText('מע"מ 18% ₪841.32');
    await expect(foot).toContainText('כולל מע"מ ₪5,515.32');
    await expect(foot).toContainText("₪1,194.50");
    await expect(foot).toContainText("שורה אחת בלי עלות לא נכללת");
    await expect(page.getByTestId("findings")).toContainText("4 ממצאים");
    await expect(page.getByTestId("findings")).toContainText("F26–F29 מופיעים בחזית ולא בתוכנית");
  });

  test("filters count, filter, toggle back and show the empty state", async ({ page }) => {
    await openNursery(page);
    await expect(page.getByTestId("filter-all")).toContainText("14");
    await expect(page.getByTestId("filter-review")).toContainText("5");
    await expect(page.getByTestId("filter-green")).toContainText("9");

    await page.getByTestId("filter-red").click();
    await expect(page.getByTestId("filter-red")).toHaveAttribute("aria-pressed", "true");
    await expect(lines(page)).toHaveCount(5);
    // Every non-green line says why (09 principle 3): here, no price
    for (const row of await lines(page).all()) await expect(row.locator(".chip.bad")).toHaveText("אין מחיר");
    await expect(lines(page).first().getByRole("img")).toHaveAccessibleName("לא זוהה או שגוי");

    await page.getByTestId("filter-red").click(); // second click: back to all
    await expect(page.getByTestId("filter-all")).toHaveAttribute("aria-pressed", "true");

    await page.getByTestId("filter-yellow").click();
    await expect(page.getByText("אין שורות שמתאימות לסינון")).toBeVisible();
    await page.getByRole("button", { name: "הצג הכל" }).click();
    await expect(page.getByTestId("filter-all")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("הזנה", { exact: true })).toBeVisible();
  });

  test("a line's detail: what the drawing says, where each value comes from, price and cost", async ({ page }) => {
    await openNursery(page);
    const f1 = await lineWith(page, "SN201M");
    await expect(f1.locator(".des")).toHaveText("F1–F17");
    await expect(f1).toContainText(isMobile(page) ? "17 × ₪130" : "₪2,210");
    await f1.click();
    const detail = isMobile(page)
      ? page.getByRole("dialog", { name: /SN201M/ }).getByTestId("line-detail")
      : page.getByTestId("line-detail");
    await expect(detail.locator(".raw")).toHaveText("F1 … F17\n10+N\nINC=8A\nSN201M");
    await expect(detail).toContainText("קטבים");
    await expect(detail).toContainText("1P+N");
    await expect(detail).toContainText("מקור: הצעה 10288");
    await expect(detail).toContainText("ספק א׳ · מפיץ ABB");
    await expect(detail).toContainText("26%");
    await expect(detail).toContainText("אין חלופות. הדגם כתוב בשרטוט");
    if (isMobile(page)) {
      await page.getByRole("button", { name: "סגירה" }).click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
    } else {
      await f1.click(); // a second click closes it
      await expect(page.getByTestId("line-detail")).toHaveCount(0);
    }
  });

  test("an inferred line explains itself", async ({ page }) => {
    await openNursery(page);
    const c1 = await lineWith(page, "מגען");
    await expect(c1.locator(".chip")).toHaveText(["הוסק מהמעגל", "אין מחיר"]);
    await c1.click();
    const detail = page.getByTestId("line-detail");
    await expect(detail).toContainText("הוסק מ-F22–F25 (3X16A)");
    await expect(detail).toContainText("כלל ההסקה בוחר את הקטן ביותר");
    await expect(detail).toContainText("מגענים C1–C4: הזרם הוסק");
    await expect(detail).toContainText("מגען 3P ‏25A");
  });

  test("the keyboard moves, opens and closes (09 §8)", async ({ page }) => {
    test.skip(isMobile(page), "the keyboard is a desktop feature (09 §8)");
    await openNursery(page);
    await page.keyboard.press("ArrowDown");
    const current = page.locator("[data-testid=line][aria-current=true]");
    await expect(current).toContainText("XT1C 4P");
    await expect(current).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(current).toContainText("ערכה");
    await page.keyboard.press("ArrowUp");
    await expect(current).toContainText("XT1C 4P");
    await page.keyboard.press("Space");
    await expect(current).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("line-detail")).toContainText("ABB XT2N 4P 160A + RC");
    await page.keyboard.press("Enter"); // reserved for "approve" (S23): nothing happens yet
    await expect(current).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("line-detail")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(current).toHaveCount(0);
  });

  test("the phone has lines, drawing and chat tabs", async ({ page }) => {
    test.skip(!isMobile(page), "tabs are the phone layout (09 §5.2)");
    await openNursery(page);
    await page.getByRole("tab", { name: "שרטוט" }).click();
    await expect(page.getByTestId("strip")).toBeVisible();
    await expect(page.getByTestId("lines-scroll")).toBeHidden();
    await page.getByRole("tab", { name: "שורות" }).click();
    await expect(page.getByTestId("lines-scroll")).toBeVisible();
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(375); // no sideways page scroll
  });
});

test.describe("states the fixture lacks (mocked answer)", () => {
  const fakeId = "quo_01JD0000000000000000000001";

  async function serve(page: Page, body: Quote) {
    await page.route(`**/quotes/${body.quote_id}`, (route) => route.fulfill({ json: body }));
    await page.goto(`/review/${body.quote_id}`);
  }

  test.beforeEach(async ({ page, request }) => {
    await signIn(page, request, TENANTS.review);
  });

  test("two panels, missing lines, accessories and labor", async ({ page }) => {
    const main = panel(
      "לוח ראשי",
      [
        line({ description: 'מא"ז מאושר', status_reasons: [{ source: "user", status: "green", value: "approved" }] }),
        line({
          description: 'מא"ז בביטחון נמוך',
          status: "yellow",
          status_reasons: [{ source: "confidence", status: "yellow", value: 0.71 }],
        }),
        line({
          line_type: "missing",
          section: "missing",
          line_group: null,
          description: 'רכיב שלא זוהה (נראה כמו מא"ז 1P 20A)',
          status: "red",
          status_reasons: [{ source: "missing", status: "red" }],
        }),
        line({ line_type: "derived", section: "extras", line_group: null, description: "פס צבירה" }),
        line({ line_type: "labor", section: "extras", line_group: null, description: "עבודת הרכבה" }),
      ],
      "925.0000",
    );
    const floor = panel("לוח קומה 2", [line({ description: 'מא"ז קומה 2' })]);
    await serve(page, { ...quote([main, floor]), quote_id: fakeId });

    const tabs = page.getByRole("tablist", { name: "לוחות" });
    await expect(tabs.getByRole("tab")).toHaveText(["לוח ראשי2", "לוח קומה 2"]);
    await expect(page.getByText("רכיבים שלא זוהו")).toBeVisible();
    await expect(page.getByText("פריטים נלווים ועבודה")).toBeVisible();
    await expect(lines(page).filter({ hasText: "פס צבירה" }).getByRole("img")).toHaveAttribute("data-shape", "box");
    await expect(lines(page).filter({ hasText: "בביטחון נמוך" }).locator(".chip")).toHaveText("ביטחון קריאה 0.71");
    await expect(lines(page).filter({ hasText: "מאושר" }).locator(".chip")).toHaveText("אושר");
    await expect(page.getByTestId("panel-total")).toContainText("סה״כ לוח ראשי לפני מע״מ₪925");

    await tabs.getByRole("tab", { name: "לוח קומה 2" }).click();
    await expect(lines(page)).toHaveCount(1);
    await expect(lines(page)).toContainText('מא"ז קומה 2');
  });

  test("150 lines are virtualized and scroll to the end", async ({ page }) => {
    const many = Array.from({ length: 150 }, (_, i) =>
      line({ description: `מא"ז מספר ${i + 1}`, designators: [`F${i + 1}`], status: i % 10 ? "green" : "red" }),
    );
    await serve(page, { ...quote([panel("לוח גדול", many, "27750.0000")]), quote_id: fakeId });
    await expect(page.getByTestId("filter-all")).toContainText("150");
    const rendered = await lines(page).count();
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(60); // only what is near the viewport is in the DOM

    const took = await scrollToEnd(page);
    await expect(page.getByTestId("panel-total")).toBeVisible();
    await expect(lines(page).filter({ hasText: "מספר 150" })).toBeVisible();
    expect(await lines(page).count()).toBeLessThan(60);
    expect(took).toBeLessThan(5_000);
  });

  test("with review_screen off the route stays a placeholder", async ({ page }) => {
    await page.route("**/me", async (route) => {
      const response = await route.fetch();
      const me = (await response.json()) as { flags: Record<string, boolean> };
      await route.fulfill({ response, json: { ...me, flags: { ...me.flags, review_screen: false } } });
    });
    await page.goto(`/review/${fakeId}`);
    await expect(page.getByText("המסך הזה עוד בבנייה.")).toBeVisible();
  });

  test("an unknown quote says so", async ({ page }) => {
    await page.goto("/review/quo_01JD0000000000000000000009");
    await expect(page.getByRole("alert")).toHaveText("ההצעה לא נמצאה");
  });
});
