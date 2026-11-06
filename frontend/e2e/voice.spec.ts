/**
 * Voice in the chat builder (13 §4.2, S27 decision 1), desktop and phone, with a tone made in the page standing in
 * for the microphone (Chromium's fake device hangs in headless on macOS) and the stand-in transcriber, which hears the prototype's sentence (`startRec`, line 1327): the home mic starts a
 * recording on /build, the card shows what was heard and what was understood, "הוסף" adds the lines and "תקן" puts
 * the words in the field. The recording is never stored (the server's tests check that).
 */
import { expect, test, type Page } from "@playwright/test";

import { signIn, TENANTS } from "./fixtures";

test.describe.configure({ timeout: 60_000 });
test.use({ launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] } });

const lines = (page: Page) => page.getByTestId("build-line");

test.describe("voice_input on", () => {
  test.beforeEach(async ({ page, request }, info) => {
    // the microphone: a tone, recorded by the page's own MediaRecorder
    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = async () => {
        const audio = new AudioContext();
        const tone = audio.createOscillator();
        const out = audio.createMediaStreamDestination();
        tone.connect(out);
        tone.start();
        return out.stream;
      };
    });
    await signIn(page, request, info.project.name === "mobile" ? TENANTS.buildMobile : TENANTS.buildDesktop);
  });

  async function recordOnce(page: Page) {
    const mic = page.getByTestId("mic");
    await expect(mic).toHaveAttribute("aria-pressed", "true");
    await expect(mic).toHaveClass(/rec/);
    await page.waitForTimeout(800);
    await mic.click();
    await expect(page.getByTestId("voice-card")).toBeVisible({ timeout: 20_000 });
  }

  test("the home mic records; what was heard and understood waits for הוסף", async ({ page }) => {
    await page.goto("/home");
    await page.getByTestId("mic-home").click();
    await expect(page).toHaveURL(/\/build$/);
    await recordOnce(page);
    await expect(page.getByTestId("build-user-msg").last()).toContainText('שמעתי: "מפסק ראשי ארבע על שישים ושלוש');
    const card = page.getByTestId("voice-card");
    await expect(card.locator("li")).toHaveCount(4);
    await expect(card).toContainText('12 × מא"ז 1X16');
    await expect(lines(page)).toHaveCount(0);
    await card.getByTestId("voice-add").click();
    await expect(lines(page)).toHaveCount(4);
    await expect(page.getByTestId("voice-card")).toHaveCount(0);
  });

  test("תקן puts what was heard in the field and adds nothing", async ({ page }) => {
    await page.goto("/build");
    await page.getByTestId("mic").click();
    await recordOnce(page);
    await page.getByTestId("voice-fix").click();
    await expect(page.getByTestId("voice-card")).toHaveCount(0);
    await expect(page.getByTestId("build-input")).toHaveValue(/^מפסק ראשי ארבע על שישים ושלוש/);
    await expect(page.getByTestId("build-input")).toBeFocused();
    await expect(lines(page)).toHaveCount(0);
  });
});
