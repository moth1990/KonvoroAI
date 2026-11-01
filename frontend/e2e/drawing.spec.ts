/**
 * The review screen's drawing pane (09 §5.2, §6.5, §7.1, §7.11, §8; S11): the NURSERY-1 fixture's pages in
 * OpenSeadragon, loaded tile by tile from the API with the token, the boxes, the strip, "show on drawing", paging,
 * zoom, the phone's drawing tab and undo. A page with two panels comes from a mocked answer.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

import type { Quote } from "../src/api/client";
import { line, page as quotePage, panel, quote } from "../src/screens/review/fixtures";
import { isMobile, signIn, TENANTS } from "./fixtures";
import { lineWith, openNursery } from "./review-helpers";

// No animation: OpenSeadragon jumps straight to where it goes (09 §13), so a measure after a click is final.
test.use({ reducedMotion: "reduce" });

const viewer = (page: Page) => page.getByTestId("viewer");
const thumb = (page: Page, no: number) =>
  page.getByTestId("page-thumb").and(page.getByLabel(new RegExp(`^עמוד ${no},`)));
const selectedBoxes = (page: Page) => page.locator("[data-testid=hl][data-selected]");

async function ready(page: Page) {
  await expect(viewer(page)).toHaveAttribute("data-state", "ready", { timeout: 20_000 });
}

async function pageIdOf(page: Page, no: number): Promise<string> {
  return (await thumb(page, no).getAttribute("data-page-id")) ?? "";
}

async function width(box: Locator): Promise<number> {
  return (await box.boundingBox())?.width ?? 0;
}

/** Clicks a box on the drawing, where a user would: OpenSeadragon takes the pointer, not the box element. */
async function clickAt(page: Page, box: Locator, yShare = 0.5): Promise<void> {
  const b = await box.boundingBox();
  if (!b) throw new Error("the box is not on screen");
  await page.mouse.click(b.x + b.width / 2, b.y + b.height * yShare);
}

/** Whether the box's centre is inside the viewer, where the user can see it. */
async function inView(page: Page, box: Locator): Promise<boolean> {
  const [b, v] = await Promise.all([box.boundingBox(), viewer(page).boundingBox()]);
  if (!b || !v) return false;
  const cx = b.x + b.width / 2;
  const cy = b.y + b.height / 2;
  return cx > v.x && cx < v.x + v.width && cy > v.y && cy < v.y + v.height;
}

test.describe("the drawing pane on the NURSERY-1 fixture", () => {
  test.beforeEach(async ({ page, request }) => {
    await signIn(page, request, TENANTS.review);
  });

  test("opens on the first decoded page, tile by tile, with the token on every request", async ({ page }) => {
    test.skip(isMobile(page), "the phone shows the drawing in its own tab");
    const tile = page.waitForRequest((r) => /\/pages\/pg_\w+\/dz\/page_files\/\d+\/\d+_\d+\.png$/.test(r.url()));
    await openNursery(page);
    const request = await tile;
    expect(request.headers()["authorization"]).toMatch(/^Bearer /);
    expect((await request.response())?.status()).toBe(200);
    await ready(page);

    const info = page.getByTestId("pageinfo");
    await expect(info).toContainText("עמוד 5 מתוך 9 · חד-קווי");
    await expect(info).toContainText("פענוח");
    await expect(info).toContainText("ביטחון 95%");
    await expect(info).toContainText("וקטורי");
    await expect(page.getByTestId("page-thumb")).toHaveCount(9);
    await expect(thumb(page, 5)).toHaveAttribute("aria-current", "true");
    await expect(thumb(page, 8)).toHaveAccessibleName("עמוד 8, חד-קווי, פענוח, 2 לא זוהו או שגויות");
    await expect(thumb(page, 8).locator(".pg-count")).toHaveText("2");
    await expect(thumb(page, 2)).toHaveClass(/skip/);
    await expect(page.locator(".pg img").first()).toHaveAttribute("loading", "lazy");

    // every instance on the page, red ones dashed (09 §13: not by color alone)
    await expect(page.getByTestId("hl")).not.toHaveCount(0);
    const red = page.locator("[data-testid=hl].r").first();
    await expect(red).toHaveCSS("stroke-dasharray", /\d/);
    await expect(page.locator("[data-testid=hl].g").first()).toHaveCSS("stroke-dasharray", "none");
  });

  test("a context page shows the image and what it is for, with no boxes", async ({ page }) => {
    test.skip(isMobile(page), "the phone flow is below");
    await openNursery(page);
    await ready(page);
    await thumb(page, 4).click();
    await expect(thumb(page, 4)).toHaveAttribute("aria-current", "true");
    await expect(viewer(page)).toHaveAttribute("data-page", await pageIdOf(page, 4));
    await ready(page);
    const info = page.getByTestId("pageinfo");
    await expect(info).toContainText("עמוד 4 מתוך 9 · חזית לוח");
    await expect(info).toContainText("משמש לבדיקה צולבת של התגים. רכיבים לא נספרים מכאן");
    await expect(page.getByTestId("hl")).toHaveCount(0);
  });

  test("selecting a line moves the drawing to its page and marks every instance (09 §7.1)", async ({ page }) => {
    test.skip(isMobile(page), "the phone flow is below");
    await openNursery(page);
    await ready(page);
    await (await lineWith(page, "AC-3")).click(); // C1–C4: page 8, 8 boxes
    await expect(viewer(page)).toHaveAttribute("data-page", await pageIdOf(page, 8));
    await expect(thumb(page, 8)).toHaveAttribute("aria-current", "true");
    await ready(page);
    await expect(selectedBoxes(page)).toHaveCount(8);
  });

  test("הצג בשרטוט frames the line on its page", async ({ page }) => {
    test.skip(isMobile(page), "the phone flow is below");
    await openNursery(page);
    await ready(page);
    await (await lineWith(page, "ממסר עזר")).click(); // RNV: pages 5 and 8
    const detail = page.getByTestId("line-detail");
    await expect(detail).toBeVisible();
    const box = selectedBoxes(page).first();
    const before = await width(box);
    await detail.getByRole("button", { name: "הצג בשרטוט" }).click();
    await expect.poll(() => width(box)).toBeGreaterThan(before * 3);
    expect(await inView(page, box)).toBe(true);
    await expect(viewer(page)).toHaveAttribute("data-page", await pageIdOf(page, 5)); // the current page has it
  });

  test("a click on a box selects its line and scrolls the table to it", async ({ page }) => {
    test.skip(isMobile(page), "the phone flow is below");
    await openNursery(page);
    await ready(page);
    const q0 = page.getByTestId("hl").filter({ hasText: "Q0" });
    await clickAt(page, q0);
    const current = page.locator("[data-testid=line][aria-current=true]");
    await expect(current).toContainText("XT1C 4P");
    await expect(current).toBeInViewport();
    await expect(q0).toHaveAttribute("data-selected", "true");
  });

  test("a finding's בשרטוט goes to its page and frames it", async ({ page }) => {
    await openNursery(page);
    await page.getByTestId("findings").getByRole("button", { name: "בשרטוט" }).click();
    await expect(viewer(page)).toBeVisible(); // on the phone, the drawing tab
    await expect(viewer(page)).toHaveAttribute("data-page", await pageIdOf(page, 4));
    await ready(page);
    const box = page.getByTestId("hl-finding");
    await expect(box).toBeVisible();
    await expect.poll(() => inView(page, box)).toBe(true);
    await expect.poll(() => width(box)).toBeGreaterThan(60);
  });

  test("PgDn / PgUp, previous / next and zoom", async ({ page }) => {
    test.skip(isMobile(page), "keys are for the desktop (09 §8)");
    await openNursery(page);
    await ready(page);
    await page.keyboard.press("PageDown");
    await expect(thumb(page, 6)).toHaveAttribute("aria-current", "true");
    await page.keyboard.press("PageUp");
    await expect(thumb(page, 5)).toHaveAttribute("aria-current", "true");
    const tools = page.getByRole("toolbar", { name: "כלי השרטוט" });
    await tools.getByRole("button", { name: "העמוד הבא" }).click();
    await expect(page.getByTestId("pageinfo")).toContainText("עמוד 6 מתוך 9");
    await tools.getByRole("button", { name: "העמוד הקודם" }).click();
    await expect(page.getByTestId("pageinfo")).toContainText("עמוד 5 מתוך 9");
    await ready(page);

    const box = page.getByTestId("hl").first();
    const fit = await width(box);
    await tools.getByRole("button", { name: "הגדל" }).click();
    await expect.poll(async () => (await width(box)) / fit).toBeCloseTo(1.5, 1); // the stroke doesn't scale
    await tools.getByRole("button", { name: "התאם לחלון" }).click();
    await expect.poll(async () => (await width(box)) / fit).toBeCloseTo(1, 1);
    await tools.getByRole("button", { name: "הקטן" }).click();
    await expect.poll(() => width(box)).toBeLessThan(fit);
  });

  test("a row select or a page change shows within 150 ms (09 §14)", async ({ page }) => {
    test.skip(isMobile(page), "measured on the desktop, where both panes are on screen");
    await openNursery(page);
    await ready(page);
    const p8 = await pageIdOf(page, 8);
    // From the click to the frame that shows the result, timed in the page.
    const took = await page.evaluate(async (target) => {
      const frame = () => new Promise((r) => requestAnimationFrame(() => r(null)));
      const until = async (done: () => boolean) => {
        const t0 = performance.now();
        for (let i = 0; i < 120 && !done(); i++) await frame();
        return performance.now() - t0;
      };
      const row = [...document.querySelectorAll<HTMLElement>("[data-testid=line]")].find((r) =>
        r.textContent?.includes("XT1C 4P"),
      );
      row?.click();
      const select = await until(() => !!document.querySelector("[data-testid=hl][data-selected]"));
      document.querySelector<HTMLElement>(`[data-page-id="${target}"]`)?.click();
      const pageChange = await until(
        () => document.querySelector("[data-testid=viewer]")?.getAttribute("data-page") === target,
      );
      return { select, pageChange };
    }, p8);
    expect(took.select).toBeLessThan(150);
    expect(took.pageChange).toBeLessThan(150);
  });

  test("undo: nothing to take back yet", async ({ page }) => {
    await openNursery(page);
    await expect(page.getByTestId("undo-last")).toBeDisabled();
    await page.locator("body").click({ position: { x: 1, y: 1 } });
    await page.keyboard.press("ControlOrMeta+z");
    await expect(page.getByTestId("toast")).toHaveText("אין מה לבטל");
  });

  test("the phone: the drawing tab, and הצג בשרטוט from the sheet", async ({ page }) => {
    test.skip(!isMobile(page), "the phone layout (09 §5.2)");
    await openNursery(page);
    await page.getByRole("tab", { name: "שרטוט" }).click();
    await ready(page);
    await expect(page.getByTestId("hl")).not.toHaveCount(0);
    await page.getByRole("tab", { name: "שורות" }).click();
    await (await lineWith(page, "ממסר עזר")).click();
    const sheet = page.getByRole("dialog");
    await sheet.getByRole("button", { name: "הצג בשרטוט" }).click();
    await expect(sheet).toBeHidden();
    await expect(page.getByRole("tab", { name: "שרטוט" })).toHaveAttribute("aria-selected", "true");
    await ready(page);
    const box = selectedBoxes(page).first();
    await expect.poll(() => inView(page, box)).toBe(true);
    await expect.poll(() => width(box)).toBeGreaterThan(60);
    const scroll = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scroll).toBeLessThanOrEqual(375); // the page never scrolls sideways; the viewer pans
  });
});

test.describe("a page with two panels (mocked answer)", () => {
  const WHITE_PNG = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC",
    "base64",
  );

  test.beforeEach(async ({ page, request }) => {
    await signIn(page, request, TENANTS.review);
    // A blank 842 × 595 page, so the viewer opens without a pyramid in S3.
    await page.route("**/pages/*/dz/page.dzi", (route) =>
      route.fulfill({
        contentType: "application/xml",
        body: '<?xml version="1.0"?><Image xmlns="http://schemas.microsoft.com/deepzoom/2008" Format="png" Overlap="1" TileSize="510"><Size Width="842" Height="595"/></Image>',
      }),
    );
    await page.route("**/pages/*/dz/page_files/**", (route) =>
      route.fulfill({ contentType: "image/png", body: WHITE_PNG }),
    );
  });

  test("frames each panel; the other one is veiled, and a click on it switches panel", async ({ page }) => {
    const shared = quotePage(3, {
      panels: [
        { panel_id: "pnl_A", name: "לוח ראשי", bbox: [20, 20, 410, 575] },
        { panel_id: "pnl_B", name: "לוח קומה 2", bbox: [430, 20, 822, 575] },
      ],
    });
    const a = line({ description: 'מא"ז ראשי', boxes: [{ page_id: shared.page_id, bbox: [100, 100, 140, 140] }] });
    const b = line({ description: 'מא"ז קומה', boxes: [{ page_id: shared.page_id, bbox: [500, 100, 540, 140] }] });
    const body: Quote = {
      ...quote(
        [
          { ...panel("לוח ראשי", [a]), panel_id: "pnl_A" },
          { ...panel("לוח קומה 2", [b]), panel_id: "pnl_B" },
        ],
        [],
        [shared],
      ),
      quote_id: "quo_01JD0000000000000000000002",
    };
    await page.route(`**/quotes/${body.quote_id}`, (route) => route.fulfill({ json: body }));
    await page.goto(`/review/${body.quote_id}`);
    if (isMobile(page)) await page.getByRole("tab", { name: "שרטוט" }).click();
    await ready(page);

    await expect(page.getByTestId("panel-frame")).toHaveCount(2);
    const veil = page.getByRole("button", { name: "מעבר ללוח לוח קומה 2" });
    await expect(veil).toHaveCount(1);
    // the other panel's line is dimmed
    await expect(page.locator(`[data-testid=hl][data-line-id="${b.line_id}"]`)).toHaveClass(/dim/);

    await clickAt(page, veil, 1 / 3); // above the veil's text
    if (isMobile(page)) await page.getByRole("tab", { name: "שורות" }).click();
    await expect(page.getByRole("tablist", { name: "לוחות" }).getByRole("tab", { name: /לוח קומה 2/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    if (isMobile(page)) await page.getByRole("tab", { name: "שרטוט" }).click();
    await expect(page.getByRole("button", { name: "מעבר ללוח לוח ראשי" })).toHaveCount(1);
  });
});
