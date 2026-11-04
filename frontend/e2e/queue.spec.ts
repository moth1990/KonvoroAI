/**
 * The pilot approval queue (00 §14.2, prototype `vQueue`, S24): the prototype's six candidates, approving one to the
 * shared layer and rejecting one, each card moving to "טופל" with its chip, and the counts. Decisions are final, so
 * the counts are read from the screen first: a retry starts with fewer pending.
 */
import { expect, test, type Page } from "@playwright/test";

import { isMobile, signIn, TENANTS } from "./fixtures";

test.describe.configure({ mode: "serial", timeout: 60_000 });

function tenant(page: Page): string {
  return isMobile(page) ? TENANTS.queueMobile : TENANTS.queueDesktop;
}

test("a candidate is approved to the shared layer and another is rejected", async ({ page, request }) => {
  await signIn(page, request, tenant(page));
  await page.goto("/queue");
  await expect(page.getByRole("heading", { name: "תור אישור", level: 1 })).toBeVisible();
  await expect(page.getByText("חודש הפיילוט: מהנדס המפעל מאשר מה עובר לשכבה המשותפת")).toBeVisible();

  const pendingSection = page.getByRole("region", { name: "ממתין לאישור" });
  const pending = pendingSection.getByTestId("qcard");
  await expect(pending.first()).toBeVisible();
  const before = await pending.count();
  expect(before).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("pending-count")).toHaveText(String(before));

  const first = pending.first();
  const approved = (await first.locator("b").textContent()) ?? "";
  await expect(first).toContainText("ראיה:");
  await expect(first).toContainText("מקור:");
  await first.getByTestId("qok").click();
  await expect(page.getByText("עבר לשכבה המשותפת, עם מקור pilot_engineer")).toBeVisible();
  await expect(page.getByTestId("pending-count")).toHaveText(String(before - 1));

  const second = pending.first();
  const rejected = (await second.locator("b").textContent()) ?? "";
  await second.getByTestId("qno").click();
  await expect(page.getByText("נדחה. נשאר רק אצלכם")).toBeVisible();
  await expect(page.getByTestId("pending-count")).toHaveText(String(before - 2));

  const handled = page.getByRole("region", { name: "טופל" });
  await expect(handled.getByTestId("qcard").filter({ hasText: approved })).toContainText("אושר · pilot_engineer");
  await expect(handled.getByTestId("qcard").filter({ hasText: rejected })).toContainText("נדחה · נשאר במפעל");
  await expect(handled.getByTestId("qok")).toHaveCount(0);

  await page.reload(); // decisions are kept
  await expect(page.getByTestId("pending-count")).toHaveText(String(before - 2));
  if (!isMobile(page)) {
    const rail = page.getByRole("link", { name: /תור אישור/ });
    if (before - 2 > 0) await expect(rail).toContainText(String(before - 2));
  }
});
