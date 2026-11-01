/**
 * Captures each built screen from the prototype and from the app, side by side, into report.html
 * (docs/dev-strategy.md §5). The user reviews the report; accepted screens become screenshot baselines.
 *
 * The prototype is opened at its hash route with localStorage set the way its own code reads it
 * (`konboro:authed`, `konboro:flags`). The app is opened as the E2E tenant in the same state.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { test, type Page } from "@playwright/test";

import { signIn, SLOW_PROJECT, TENANTS } from "../fixtures";
import { lineWith } from "../review-helpers";
import { prototypePort } from "./fidelity.config";

const OUT = fileURLToPath(new URL("./out/", import.meta.url));
const REPORT = fileURLToPath(new URL("./report.html", import.meta.url));
const PROTOTYPE = `http://127.0.0.1:${prototypePort}/konboro-app.html`;

interface Screen {
  id: string;
  title: string;
  /** `setup` runs after the page opens: clicks that bring the screen into the state to compare. */
  prototype: { hash: string; authed: boolean; flags?: Record<string, boolean>; setup?: (page: Page) => Promise<void> };
  app: { path: string; tenant?: string; setup?: (page: Page) => Promise<void> };
  notes: string[];
  /** The window as it is, not the whole page: the drawing viewer fills the window and would collapse unrolled. */
  window?: boolean;
}

const NURSERY = fileURLToPath(new URL("../../../golden/NURSERY-1/NURSERY-1.pdf", import.meta.url));
const NEVIS = fileURLToPath(new URL("../../../golden/NEVIS-1/NEVIS-1.pdf", import.meta.url));
const PROJECT = "גן ילדים, לוח ראשי";

/** The prototype's new-quote screen with NURSERY-1 and a DWG picked (its built-in sample files). */
async function prototypePick(page: Page) {
  await page.locator("#up-proj").fill(PROJECT);
  await page.locator("#samples summary").click();
  await page.locator('[data-act="sample"][data-i="0"]').click();
  await page.locator('[data-act="sample"][data-i="1"]').click();
  if (await page.locator("#samples[open]").count()) await page.locator("#samples summary").click();
}

async function appPick(page: Page) {
  await page.getByLabel("פרויקט / שם הלוח").fill(PROJECT);
  await page.locator("#file-in").setInputFiles([
    { name: "NURSERY-1.pdf", mimeType: "application/pdf", buffer: readFileSync(NURSERY) },
    { name: "MAIN_BOARD.dwg", mimeType: "application/octet-stream", buffer: Buffer.from("AC1027") },
  ]);
}

async function prototypeStart(page: Page) {
  await page.locator("#up-proj").fill(PROJECT);
  await page.locator("#samples summary").click();
  await page.locator('[data-act="sample"][data-i="0"]').click();
  await page.locator('[data-act="start"]').click();
}

async function appStart(page: Page, project: string) {
  await page.getByLabel("פרויקט / שם הלוח").fill(project);
  await page.locator("#file-in").setInputFiles(NURSERY);
  await page.getByTestId("start").click();
}

const NEW_QUOTE_NOTES = [
  'Left out on purpose: the "קבצים לדוגמה" sample files (01 §4.6 item 5: demo only).',
  "Page counts appear once the server has checked the file; the browser checks only type and size.",
];

const SCREENS: Screen[] = [
  {
    id: "login",
    title: "Login",
    prototype: { hash: "", authed: false },
    app: { path: "/login" },
    notes: [
      'Left out on purpose: the demo hint ("בדמו: …") and the "אב טיפוס · שרת מדומה" tag.',
      'Fixed: in the prototype the password placeholder runs under the "הצג" button; the app keeps room for it.',
      "The prototype page has an 8px margin around it (no body reset); the app is edge to edge.",
    ],
  },
  {
    id: "home-classic",
    title: "Home, classic (home_chat off) and shell",
    prototype: { hash: "#home", authed: true, flags: { home_chat: false } },
    app: { path: "/home", tenant: TENANTS.classic },
    notes: [
      "Data differs by design: the app shows the E2E tenant's made-up quotes, not the prototype's demo projects.",
      'Coverage and "approved without correction" read "—" until S22/S23 (S04 decision).',
      'The "אב טיפוס · נתוני דוגמה" tag in the top bar is left out.',
      "The prototype underlines the text of its link-buttons (a.btn has no text-decoration rule); the app does not.",
      'Phone tab bar: the app adds the approval-queue count on "תור"; the prototype shows it in the rail only.',
    ],
  },
  {
    id: "home-chat",
    title: "Home, chat (home_chat on)",
    prototype: { hash: "#home", authed: true, flags: { home_chat: true } },
    app: { path: "/home", tenant: TENANTS.chat },
    notes: [
      "No mic button until voice lands (S27).",
      "The suggestion about the NURSERY demo quote is left out; the weekday is today's, in the tenant's timezone.",
    ],
  },
  {
    id: "new-pick",
    title: "New quote: pick (NURSERY-1 and a DWG)",
    prototype: { hash: "#new", authed: true, setup: prototypePick },
    app: { path: "/new", tenant: TENANTS.uploadDesktop, setup: appPick },
    notes: NEW_QUOTE_NOTES,
  },
  {
    id: "new-run",
    title: "New quote: run (mid-pipeline)",
    prototype: {
      hash: "#new",
      authed: true,
      setup: async (page) => {
        await prototypeStart(page);
        await page.waitForTimeout(1500); // the prototype advances a stage every 650 ms
      },
    },
    app: {
      path: "/new",
      tenant: TENANTS.uploadMobile,
      setup: async (page) => {
        await appStart(page, SLOW_PROJECT);
        await page.locator('[data-testid="stage-2"][data-state="run"]').waitFor({ timeout: 20_000 });
      },
    },
    notes: [
      "Stage summaries under finished stages: the app has one for stage 1 so far; the other stages are stubs (S08+).",
    ],
  },
  {
    id: "new-done",
    title: "New quote: done",
    prototype: {
      hash: "#new",
      authed: true,
      setup: async (page) => {
        await prototypeStart(page);
        await page.locator('[data-act="toreview"]').waitFor({ timeout: 15_000 });
      },
    },
    app: {
      path: "/new",
      tenant: TENANTS.uploadMobile,
      setup: async (page) => {
        await appStart(page, PROJECT);
        await page.getByTestId("done").waitFor({ timeout: 30_000 });
        await page.waitForFunction(() => [...document.images].every((img) => img.complete));
      },
    },
    notes: [
      "The result tile reads 0 products until stages 4–7 are real.",
      "Page kinds come from stage 1 (S08). In E2E the model is a stand-in that classifies like NURSERY-1's labels, so " +
        "the routes match the prototype's: 5 process, 2 context, 2 skip.",
      "The kind select lists the 11 kinds of 01 §5.4 (spec keys win); the prototype lists 7 Hebrew labels, one of them " +
        '"חד-קווי ופיקוד", which is not a kind.',
      "The note under each card follows how the page was classified (template, reused, low confidence, by the user).",
    ],
  },
  {
    id: "new-confirm",
    title: "New quote: confirm pages (no prototype screen; compared with the done step)",
    prototype: {
      hash: "#new",
      authed: true,
      setup: async (page) => {
        await prototypeStart(page);
        await page.locator('[data-act="toreview"]').waitFor({ timeout: 15_000 });
      },
    },
    app: {
      path: "/new",
      tenant: TENANTS.uploadDesktop,
      setup: async (page) => {
        await page
          .locator("#file-in")
          .setInputFiles({ name: "unsure-NEVIS-1.pdf", mimeType: "application/pdf", buffer: readFileSync(NEVIS) });
        await page.getByTestId("start").click();
        await page.getByTestId("confirm-pages").waitFor({ timeout: 30_000 });
        await page.waitForFunction(() => [...document.images].every((img) => img.complete));
      },
    },
    notes: [
      "01 §5.6 asks for a confirmation screen; the prototype has none. S08 decision: the done step's page grid, a line " +
        'saying why, the unsure pages marked in the warning colour, and "אשר והמשך".',
      'The chip reads "ממתין לאישור" (warning) where the done step reads "הפענוח הסתיים".',
    ],
  },
  ...reviewScreens(),
];

/** From the app's home to the NURSERY-1 fixture quote (S09), the way a user gets there. */
async function appReview(page: Page) {
  await page
    .getByTestId("recent")
    .getByRole("link", { name: /NURSERY/ })
    .click();
  await page.getByTestId("rv-totals").waitFor();
}

function reviewScreens(): Screen[] {
  const notes = [
    'Header: export, chat and "אשר ושלח" are left out until their sessions (S23, S25). The drawing pane is S11 ' +
      "(its own screens below).",
    "S09 decision 3: a shape icon beside each stripe (check, triangle, X, box), so color is never the only signal.",
    'S09 decision 4: the spec\'s filter row (הכל · רק לבדיקה · ירוק · צהוב · אדום) and the "X מתוך Y שורות מוכנות" bar.',
    "S09 decision 5: after the groups, a panel total row (09 §6.3). The prototype's footnote about accessories " +
      "included in the enclosure comes back with accessory lines (S22).",
    'S09 decision 6: on the phone a row keeps its total, and "qty × unit price" moves to the sub line.',
    "Read-only until S23: no price inputs (an unpriced line shows —), no price hints, no finding buttons.",
    "Findings are listed errors first. Runs of 3+ tags are one chip: F18–F21 here, four chips in the prototype.",
    'The prototype marks the lamps "מחיר חדש במחירון: ₪23" (its markup rule against its own fixed price); the app ' +
      "has no such state until pricing (S22).",
    "Foot totals keep agorot (₪841.32, ₪5,515.32): the prototype rounds VAT to whole shekels in the browser.",
    "Data differs by design in the rail: the E2E tenant has no approval-queue items.",
  ];
  const review = { path: "/home", tenant: TENANTS.review };
  const phone = (page: Page) => (page.viewportSize()?.width ?? 0) <= 860;
  const drawingReady = (page: Page) =>
    page.locator("[data-testid=viewer][data-state=ready]").waitFor({ timeout: 20_000 });
  const drawingNotes = [
    "S11 decision 1: every component is boxed in its line's color, red dashed; the prototype boxes only the " +
      "selected line. A click on a box selects its line.",
    "S11 decision 2: the fixture's pages are the prototype's own images, so they match; real drawings are rendered " +
      "by stage 2 and zoom sharp.",
    "S11 decision 4: \"עמוד x מתוך y\" and previous / next, each thumbnail's red (or yellow) count, and the page's " +
      "route, confidence and vector or scanned beside its title. Zoom is free; the buttons step ×1.5.",
    "The header's undo button (09 §7.11) is in; it stays disabled until S23's actions.",
  ];
  return [
    {
      id: "review-drawing",
      title: "Review: the drawing (page 5)",
      prototype: {
        hash: "#review",
        authed: true,
        setup: async (p) => {
          if (phone(p)) await p.locator('[data-act="tab"][data-tab="drawing"]').click();
        },
      },
      app: {
        ...review,
        setup: async (page) => {
          await appReview(page);
          if (phone(page)) await page.getByRole("tab", { name: "שרטוט" }).click();
          await drawingReady(page);
        },
      },
      notes: drawingNotes,
      window: true,
    },
    {
      id: "review-showdraw",
      title: 'Review: "הצג בשרטוט" on RNV',
      prototype: {
        hash: "#review",
        authed: true,
        setup: async (p) => {
          await p.locator('[data-line="rnv"]').click();
          await p.locator('[data-act="showdraw"][data-id="rnv"]').click();
        },
      },
      app: {
        ...review,
        setup: async (page) => {
          await appReview(page);
          await (await lineWith(page, "ממסר עזר")).click();
          await page.getByRole("button", { name: "הצג בשרטוט" }).click();
          await drawingReady(page);
        },
      },
      notes: [
        "Framed the prototype's way: the component a third of the view. On the phone the sheet closes and the drawing " +
          "tab opens (09 §5.2).",
      ],
      window: true,
    },
    {
      id: "review-finding",
      title: 'Review: a finding\'s "בשרטוט" (F26–F29, page 4)',
      prototype: { hash: "#review", authed: true, setup: (p) => p.locator('[data-act="f-show"]').first().click() },
      app: {
        ...review,
        setup: async (page) => {
          await appReview(page);
          await page.getByTestId("f-show").click();
          await drawingReady(page);
        },
      },
      notes: [
        "A context page: the image with its role in a chip, and no component boxes; the finding's box only.",
        "The finding's other buttons (התעלם, הוסף 4 שורות) wait for S23.",
      ],
      window: true,
    },
    {
      id: "review-lines",
      title: "Review: lines (NURSERY-1 fixture)",
      prototype: { hash: "#review", authed: true },
      app: { ...review, setup: appReview },
      notes,
    },
    {
      id: "review-detail",
      title: "Review: line detail (F1–F17)",
      prototype: { hash: "#review", authed: true, setup: (p) => p.locator('[data-line="f1"]').click() },
      app: {
        ...review,
        setup: async (page) => {
          await appReview(page);
          await page.getByTestId("line").filter({ hasText: "SN201M" }).click();
          await page.getByTestId("line-detail").waitFor();
        },
      },
      notes: [
        "S09 decision 7: read-only. No price and cost inputs, no supplier select, no החלף / מחק. הצג בשרטוט is in since S11.",
        "On the phone the detail opens in a bottom sheet (09 §5.2); the prototype expands the row.",
      ],
    },
    {
      id: "review-red",
      title: "Review: the red filter",
      prototype: { hash: "#review", authed: true, setup: (p) => p.locator('[data-act="filter"][data-f="r"]').click() },
      app: {
        ...review,
        setup: async (page) => {
          await appReview(page);
          await page.getByTestId("filter-red").click();
        },
      },
      notes: ['Every red line says why: here, "אין מחיר" on all five.'],
    },
  ];
}

// `FIDELITY_ONLY=new-pick,new-run` captures just those screens.
const ONLY = process.env.FIDELITY_ONLY?.split(",").filter(Boolean);

const VIEWPORTS = [
  { id: "desktop", width: 1440, height: 900 },
  { id: "mobile", width: 375, height: 812 },
] as const;
const SCHEMES = ["light", "dark"] as const;

// Both apps scroll inside .main; let the page grow instead, so a full-page shot shows everything.
const UNROLL = `html,body,#root,#app{height:auto!important}
.shell{height:auto!important;min-height:100vh}.main{height:auto!important;overflow:visible!important}`;

async function shoot(page: Page, file: string, window = false) {
  await page.waitForLoadState("networkidle");
  if (!window && (await page.locator(".shell").count())) await page.addStyleTag({ content: UNROLL });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${OUT}${file}`, fullPage: !window, animations: "disabled" });
}

/** Screenshots go inside the report, so it opens anywhere as one file. */
const inline = (file: string) => `data:image/png;base64,${readFileSync(`${OUT}${file}`).toString("base64")}`;

const shots: { screen: Screen; viewport: string; scheme: string; file: string }[] = [];

test.beforeAll(() => mkdirSync(OUT, { recursive: true }));

for (const screen of SCREENS.filter((s) => !ONLY || ONLY.includes(s.id))) {
  for (const viewport of VIEWPORTS) {
    for (const scheme of SCHEMES) {
      const name = `${screen.id}-${viewport.id}-${scheme}`;
      test(name, async ({ browser }) => {
        const options = {
          viewport: { width: viewport.width, height: viewport.height },
          colorScheme: scheme,
          locale: "he-IL",
          timezoneId: "Asia/Jerusalem",
          isMobile: viewport.id === "mobile",
          hasTouch: viewport.id === "mobile",
          reducedMotion: "reduce" as const, // the drawing viewer jumps straight to where it goes
        };

        // The prototype has no viewport meta, so mobile emulation would lay it out at 980px: give it a plain
        // 375px-wide window instead, which is what its CSS was written for.
        const proto = await browser.newContext({ ...options, isMobile: false });
        const p = await proto.newPage();
        const { authed, flags, hash } = screen.prototype;
        await p.addInitScript(
          ([a, f]) => {
            localStorage.clear();
            if (a) localStorage.setItem("konboro:authed", "1");
            if (f) localStorage.setItem("konboro:flags", f);
          },
          [authed, flags ? JSON.stringify(flags) : ""] as const,
        );
        await p.goto(`${PROTOTYPE}${hash}`);
        await screen.prototype.setup?.(p);
        await shoot(p, `${name}-prototype.png`, screen.window);
        await proto.close();

        const app = await browser.newContext({ ...options, baseURL: test.info().project.use.baseURL });
        const a = await app.newPage();
        if (screen.app.tenant) await signIn(a, app.request, screen.app.tenant);
        await a.goto(screen.app.path);
        await screen.app.setup?.(a);
        await shoot(a, `${name}-app.png`, screen.window);
        await app.close();

        shots.push({ screen, viewport: viewport.id, scheme, file: name });
      });
    }
  }
}

test.afterAll(() => {
  const sections = SCREENS.filter((s) => shots.some((shot) => shot.screen.id === s.id))
    .map((screen) => {
      const rows = shots
        .filter((s) => s.screen.id === screen.id)
        .map(
          (s) => `
      <h3>${s.viewport} · ${s.scheme}</h3>
      <div class="pair ${s.viewport}">
        <figure><figcaption>Prototype</figcaption><img src="${inline(`${s.file}-prototype.png`)}" alt="prototype ${s.file}"></figure>
        <figure><figcaption>App</figcaption><img src="${inline(`${s.file}-app.png`)}" alt="app ${s.file}"></figure>
      </div>`,
        )
        .join("");
      const notes = screen.notes.map((n) => `<li>${n}</li>`).join("");
      return `<section><h2>${screen.title}</h2><ul class="notes">${notes}</ul>${rows}</section>`;
    })
    .join("");
  writeFileSync(
    REPORT,
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Konboro fidelity report</title>
<style>
  body{font:14px/1.5 system-ui,sans-serif;margin:24px;background:#f4f5f7;color:#17202b}
  h1{margin:0 0 4px} h2{margin:32px 0 4px;border-top:1px solid #ccd;padding-top:16px} h3{margin:16px 0 6px;font-weight:500}
  .pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}
  .pair.mobile{grid-template-columns:repeat(2,minmax(0,400px))}
  figure{margin:0;background:#fff;border:1px solid #ccd;border-radius:8px;padding:8px}
  figcaption{font-weight:600;margin-bottom:6px}
  img{width:100%;display:block;border:1px solid #e3e6eb}
  .notes{color:#4a5566}
</style></head><body>
<h1>Prototype fidelity</h1>
<p>Generated ${new Date().toISOString()} by <code>make fidelity</code>. Left: prototype/konboro-app.html. Right: the app on the E2E API.
Phone layout starts at 860px in the app (09 §5.2), 820px in the prototype.</p>
${sections}
</body></html>`,
  );
});
