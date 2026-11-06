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

import { AUDITS, signIn, SLOW_PROJECT, TENANTS } from "../fixtures";
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
  ...auditScreens(),
  ...priceScreens(),
  ...s24Screens(),
  ...chatScreens(),
  ...s26Screens(),
];

/** S25: the chat drawer (prototype `vChat`, `propCard`), on the desktop over the drawing, on the phone its tab. The
 * app's answers come from the stand-in model, so the words differ; the layout, the chips and the card are compared. */
function chatScreens(): Screen[] {
  const isPhone = (page: Page) => (page.viewportSize()?.width ?? 0) <= 860;
  const protoAsk = (q: string) => async (page: Page) => {
    await page.locator(isPhone(page) ? '[data-act="tab"][data-tab="chat"]' : '.rv-head [data-act="chat"]').click();
    await page.locator(`[data-act="ask"][data-q='${q}']`).click();
  };
  const appAsk = (q: string, wait: string) => async (page: Page) => {
    await appReview(page);
    if (isPhone(page)) await page.getByRole("tab", { name: "צ'אט" }).click();
    else await page.getByTestId("chat-toggle").click();
    await page.getByTestId("newchat").click(); // each shot starts its own conversation
    await page.getByTestId("ask").filter({ hasText: q }).click();
    await page.locator(wait).last().waitFor({ timeout: 15_000 });
  };
  // S25b: a typed question, with a line selected first when it is about one line
  const appType = (q: string, wait: string, line?: string) => async (page: Page) => {
    await appReview(page);
    if (line) {
      await (await lineWith(page, line)).click();
      if (isPhone(page)) await page.keyboard.press("Escape");
    }
    if (isPhone(page)) await page.getByRole("tab", { name: "צ'אט" }).click();
    else await page.getByTestId("chat-toggle").click();
    await page.getByTestId("newchat").click();
    await page.getByTestId("chat-input").fill(q);
    await page.getByTestId("chat-input").press("Enter");
    await page.locator(wait).last().waitFor({ timeout: 15_000 });
  };
  const notes = [
    "The answers come from the stand-in model (devtools/fake_llm.py): its words differ from the prototype's demo " +
      "text. Line names are chips that select the line; amounts are the server's, never the model's.",
    'Each shot starts a new conversation, so the note "שיחות קודמות נשמרו לקריאה בלבד" shows under the header.',
    'S25 decision 6: the fourth suggestion is "תראה לי את השורות האדומות"; the prototype\'s closes a finding, which ' +
      "is not one of 08 §6.7's changes.",
  ];
  return [
    {
      id: "chat-answer",
      title: "Chat: an answer with line chips",
      prototype: { hash: "#review", authed: true, setup: protoAsk("מה חסר כדי לשלוח?") },
      app: { path: "/home", tenant: TENANTS.chatShots, setup: appAsk("מה חסר כדי לשלוח?", "[data-testid=line-ref]") },
      notes,
      window: true,
    },
    {
      id: "chat-proposal",
      title: "Chat: a proposal card",
      prototype: { hash: "#review", authed: true, setup: protoAsk('החלף את כל מא"זי ABB ל-Schneider') },
      app: { path: "/home", tenant: TENANTS.chatShots, setup: appAsk("Schneider", "[data-testid=proposal]") },
      notes: [
        ...notes,
        "S25 decision 2: the card adds the totals before and after (08 §7.3) under its rows, and a reason under each " +
          "line that does not change. The prototype's card says every line turns red; the app's says what the " +
          "catalog and the price list give.",
        'S25b decision 2: the memory choice, three of the prototype\'s chips under the rows, "רק בהצעה הזו" selected; ' +
          'NURSERY has no customer, so "לזכור ללקוח הזה" is not offered. The prototype\'s card has none.',
      ],
      window: true,
    },
    {
      id: "chat-explain",
      title: "Chat: why, about one line (S25b)",
      prototype: { hash: "#review", authed: true, setup: protoAsk("למה המגענים צהובים?") },
      app: {
        path: "/home",
        tenant: TENANTS.chatShots,
        setup: appType("למה 3 קטבים?", "[data-testid=instance-ref]", "S203M 3P ‏16A"),
      },
      notes: [
        ...notes,
        "S25b: explain_line answers from the line's trace and the drawing around it (08 §6.4). The prototype's " +
          'answer to its first suggestion is the closest it has: its "פתח את C1–C4" button is the app\'s "בשרטוט" ' +
          'chip and "הצג בשרטוט" button, which frame the component on the drawing.',
      ],
      window: true,
    },
    {
      id: "chat-compare",
      title: "Chat: compare with another quote (S25b)",
      prototype: { hash: "#review", authed: true, setup: protoAsk("למה המגענים צהובים?") },
      app: {
        path: "/home",
        tenant: TENANTS.chatShots,
        setup: appType("תשווה להצעה הקודמת", "[data-testid=quote-ref]"),
      },
      notes: [
        ...notes,
        "S25b decision 1: the other quote is a chip with its name, which only the screen knows; the model knew it as " +
          "QT1. The prototype has no compare; its first answer is shown for the bubble's layout.",
      ],
      window: true,
    },
  ];
}

/** S24: the settings screen and the approval queue, in a tenant nothing changes; and the onboarding page, which the
 * prototype does not have (compared with its settings screen, whose classes it uses). */
function s24Screens(): Screen[] {
  return [
    {
      id: "prefs",
      title: "Settings",
      prototype: { hash: "#prefs", authed: true },
      app: { path: "/prefs", tenant: TENANTS.s24Shots, setup: (page) => page.getByLabel("תוספת באחוזים").waitFor() },
      notes: [
        "S24 decision 2: two brand selects, breakers and RCDs, each with 'ללא העדפה' (the spec's two families); the " +
          "prototype has one select for both.",
        "S03 decision: the flags are shown as switches that cannot be changed (the server sets them per factory); the " +
          "prototype's switches toggle in the browser. The section's note says so.",
        "The plan chip is the tenant's plan ('ניסיון'); the prototype says 'פיילוט'. The quota is the E2E tenant's 12 / 50.",
        "The E2E tenant has no RCD default, so the 30 mA switch is off; the prototype's is on.",
        "Fixed: the prototype's quota reads '50 / 12' (its numbers are not isolated from the RTL row); the app's is '12 / 50'.",
      ],
    },
    {
      id: "queue",
      title: "Approval queue",
      prototype: { hash: "#queue", authed: true },
      app: { path: "/queue", tenant: TENANTS.s24Shots, setup: (page) => page.getByTestId("qcard").last().waitFor() },
      notes: [
        "The six candidates are the prototype's (devtools/fixtures/queue.py), pending oldest first, so the order " +
          "differs; the source line gives each a date ('28.10') where the prototype says 'היום' for two.",
        "The prototype's 'ייבוא מהצעה 10271' card has no date; the app's has one.",
      ],
    },
    {
      id: "welcome",
      title: "Onboarding: two questions and the data terms (no prototype screen; compared with settings)",
      prototype: { hash: "#prefs", authed: true },
      app: {
        path: "/welcome",
        tenant: TENANTS.welcomeDesktop,
        setup: (page) => page.getByTestId("welcome-start").waitFor(),
      },
      notes: [
        "10 §5.1 asks for two questions and the data terms before the first drawing; the prototype has no screen for " +
          "them. S24 decision 1: a full page on first login, built from the prototype's card, input and button classes.",
        "Shot before the welcome tests answer it; after them the tenant is answered and the page sends it home.",
      ],
    },
  ];
}

/** The price list (S19), in a tenant nothing changes: the demo's products (the prototype's `CATALOG`). */
function priceScreens(): Screen[] {
  const prices = { path: "/prices", tenant: TENANTS.pricesShots };
  const listed = (page: Page) => page.getByTestId("prod").last().waitFor();
  return [
    {
      id: "prices",
      title: "Price list",
      prototype: { hash: "#prices", authed: true },
      app: { ...prices, setup: listed },
      notes: [
        "Rows are in family order, then name (S18's API); the prototype keeps its array's order.",
        "Families are the attribute schemas' codes with Hebrew names (S19): 'מא\"ז', 'מפסק' and 'מגן מנוע' are " +
          "one family, circuit_breaker, shown as 'מא\"ז / מפסק'; 'אביזר' is 'מגע עזר'.",
        "Money keeps agorot (₪31.50); the prototype rounds to whole shekels.",
        "The source column says where a product came from ('מהצעה קודמת', 'מחירון ספק', 'הוזן ב…'); the prototype " +
          "names quote numbers the demo seed does not keep. Its date is the last change, empty until one.",
        "The bulk discount offers the master catalog's brands with a list price (ABB in the sample), filled with " +
          "the saved discount; saving an empty field removes it.",
        "Data differs by design in the rail: the E2E tenant has no approval-queue items.",
      ],
    },
    {
      id: "prices-editor",
      title: "Price list: product editor (S203M-C16, two suppliers)",
      prototype: {
        hash: "#prices",
        authed: true,
        setup: (p) => p.locator('[data-act="prod"][data-id="s203_16"]').click(),
      },
      app: {
        ...prices,
        setup: async (page) => {
          await listed(page);
          await page.getByTestId("prod").filter({ hasText: "S203M-C16" }).click();
          await page.getByTestId("ed-drafts").waitFor();
        },
      },
      notes: [
        "Family is a list (S19): the codes margin rules and supplier preferences match on, with Hebrew names.",
        "S19 decision 1: a rule with no supplier saves, with 'בלי ספק אין עלות, ולכן אין מחיר'.",
        "S19 decision 2: 'כלול בארון' is five checkboxes on a cabinet (not this product).",
        "S19 decision 4: a typed cost is checked on blur; a warning shows in a row under the supplier (not in this shot).",
        "The drafts note lists the NURSERY lines that use the product; the prototype's names NURSERY's open draft too.",
        "The history appears after the first change; this product has none yet.",
      ],
    },
  ];
}

/** The 26-993 audit fixture (S16), in a tenant nothing changes. */
function auditScreens(): Screen[] {
  const audit = { path: `/audit/${AUDITS[TENANTS.auditShots]}`, tenant: TENANTS.auditShots };
  return [
    {
      id: "audit",
      title: "Audit: results (26-993, quote 10271)",
      prototype: { hash: "#audit", authed: true },
      app: { ...audit, setup: (page) => page.getByTestId("audit-headline").waitFor() },
      notes: [
        "Data differs by design (S16 decision 2): the app shows what the pipeline finds on replay, not the factory's " +
          "confirmed list. QG2 short (₪1,250) and an untagged CT are shown; the shunt trips and 4 more are under " +
          '"לבדוק" below 0.6 (BUG-031). So "15 / 17" is "13 / 17", 3 omissions are 2, and 6 units are 2.',
        "Added from 11 §7 in the prototype's style (S16 decision 1): the headline sentence above the KPIs, a " +
          '"החלטה" column ("נכון, זה הבדל" / "לא נכון" with a reason), each difference\'s message under its chip, ' +
          '"הצג בשרטוט" in the evidence cell, and the "לבדוק" section. No "הורד דוח".',
        'The not-a-difference rows are named by their family ("מהדק"); the prototype\'s "מהדק בדיקה למשנה זרם" ' +
          "needs a name stage 4 doesn't give.",
      ],
    },
    {
      id: "audit-evidence",
      title: "Audit: show on drawing",
      prototype: { hash: "#review", authed: true },
      app: {
        ...audit,
        setup: async (page) => {
          await page.getByRole("button", { name: "הצג בשרטוט: מפסק 4X125A" }).click();
          await page.getByTestId("evidence-drawing").locator(".hl").first().waitFor();
        },
      },
      window: true,
      notes: [
        "No prototype screen: the review screen's drawing pane (prototype `vReview`) in a dialog, QG1 and QG2 " +
          "framed in red on page 3. Compare the pane, not the page around it.",
      ],
    },
    {
      id: "audit-new",
      title: "Audit: new audit (pick)",
      prototype: { hash: "#new", authed: true },
      app: { path: "/audit", tenant: TENANTS.auditShots },
      notes: [
        "No prototype screen (S16 decision 4): the new-quote screen's pick step in its look, with two drop zones, " +
          'the drawing and the existing quote. The prototype\'s #audit has only a "בדיקה חדשה" toast.',
      ],
    },
  ];
}

/** From the app's home to the NURSERY-1 fixture quote (S09), the way a user gets there. */
async function appReview(page: Page) {
  await page
    .getByTestId("recent")
    .getByRole("link", { name: /NURSERY/ })
    .filter({ hasNotText: "הצעה קודמת" }) // the chat tenants' earlier quote, for compare (S25b)
    .click();
  await page.getByTestId("rv-totals").waitFor();
}

function reviewScreens(): Screen[] {
  const notes = [
    'Header: "אשר ושלח" since S23, the chat since S25, "הורדה" since S26 (its modal below). The drawing pane is S11 ' +
      "(its own screens below).",
    "S09 decision 3: a shape icon beside each stripe (check, triangle, X, box), so color is never the only signal.",
    'S09 decision 4: the spec\'s filter row (הכל · רק לבדיקה · ירוק · צהוב · אדום) and the "X מתוך Y שורות מוכנות" bar.',
    "S09 decision 5: after the groups, a panel total row (09 §6.3). The footnote about what the enclosure's price " +
      "includes is the factory's setting (S23 decision 19).",
    'S09 decision 6: on the phone a row keeps its total, and "qty × unit price" moves to the sub line.',
    "S23: a line with no price takes it in its row (on the phone in place of the total, decision 3); the findings " +
      'have "הצג רק אותן", "פתח את השורה" and "דחה…" (with a reason, decision 7) instead of one button per reason.',
    '"N מחירים חדשים במחירון" in the filter row opens the recalculation\'s comparison (S23 decision 15, no prototype ' +
      "screen).",
    "Findings are listed errors first. Runs of 3+ tags are one chip: F18–F21 here, four chips in the prototype.",
    'The lamps show "מחיר חדש במחירון: ₪22.50": the E2E tenant rounds to the agora; the prototype and the demo ' +
      "tenant round to the shekel (₪23, S22 decision 2).",
    "\"5 שורות בלי מחיר\" is stage 7's warning since S23 (decision 13), so it follows the front view's, as in the " +
      "prototype.",
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
    "The header's undo button (09 §7.11) is enabled once an action is on the stack (S23).",
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
        'S23 decision 7: "דחה…" opens a reason (מכוון, הבודק טעה, אחר). "הוסף 4 שורות" waits for the product ' +
          "picker (S23b).",
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
        "S23: the price with עדכן, the cost and supplier (the product's suppliers, its cost, margin and floor), " +
          '"החלף" with its key, the quantity, "אשר שורה" and "מחק שורה". הצג בשרטוט is in since S11.',
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
    {
      id: "review-send",
      title: "Review: אשר ושלח (09 §7.12)",
      prototype: { hash: "#review", authed: true, setup: (p) => p.locator('[data-act="send"]').click() },
      app: {
        ...review,
        setup: async (page) => {
          await appReview(page);
          await page.getByTestId("send").click();
          await page.getByRole("dialog").waitFor();
        },
      },
      notes: [
        "The one dialog that asks first. The app adds the margin (09 §7.12) and counts the lines with no price as left " +
          "out of the sum.",
      ],
    },
    {
      id: "review-price",
      title: "Review: לעדכן גם במחירון? (09 §7.14)",
      prototype: {
        hash: "#review",
        authed: true,
        setup: async (p) => {
          await p.locator('[data-line="f22"]').click();
          await p.locator("#edit-f22").fill("190");
          await p.locator('[data-act="editprice"][data-id="f22"]').click();
        },
      },
      app: {
        ...review,
        setup: async (page) => {
          await appReview(page);
          await (await lineWith(page, "S203M 3P \u200f16A")).click();
          await page.getByLabel("מחיר מכירה ליחידה").fill("190");
          await page.getByTestId("editprice").click();
          await page.getByRole("dialog", { name: "לעדכן גם במחירון?" }).waitFor();
        },
      },
      notes: ["On the phone the dialog opens over the line's sheet."],
    },
    {
      id: "review-locked",
      title: "Review: a sent version, locked (07 §7.7)",
      prototype: {
        hash: "#review",
        authed: true,
        setup: async (p) => {
          await p.locator('[data-act="send"]').click();
          await p.locator('[data-act="dosend"]').click();
        },
      },
      app: {
        ...review,
        setup: async (page) => {
          // the shared fixture is never sent: the quote's answer says it was
          await page.route(/\/quotes\/quo_[0-9A-Z]{26}$/, async (route) => {
            const response = await route.fetch();
            const body = (await response.json()) as Record<string, unknown>;
            await route.fulfill({ response, json: { ...body, status: "sent" } });
          });
          await appReview(page);
          await page.getByTestId("locked").waitFor();
        },
      },
      notes: ["No price cell, no action in the detail, and undo is cleared: nothing before sending is undone."],
    },
  ];
}

/** S26: the "לא פוענח" layer (13 §4.4) and the export modal (13 §4.1) on the review fixture, in the read-only review
 * tenant; and the settings screen's "המסמך ללקוח", which the prototype does not have. */
function s26Screens(): Screen[] {
  const phone = (page: Page) => (page.viewportSize()?.width ?? 0) <= 860;
  const review = { path: "/home", tenant: TENANTS.review };
  const protoPage = (n: number) => async (p: Page) => {
    if (phone(p)) await p.locator('[data-act="tab"][data-tab="drawing"]').click();
    await p.locator(`[data-act="page"][data-p="${n}"]`).click();
  };
  const appPage = (n: number) => async (page: Page) => {
    await appReview(page);
    if (phone(page)) await page.getByRole("tab", { name: "שרטוט" }).click();
    await page
      .getByTestId("page-thumb")
      .and(page.getByLabel(new RegExp(`^עמוד ${n},`)))
      .click();
    await page.locator("[data-testid=viewer][data-state=ready]").waitFor({ timeout: 20_000 });
    await page.getByTestId("ux").first().waitFor();
  };
  const layerNotes = [
    "S26 decision 5: the prototype draws its boxes from b[1]…b[4], as if they began with a page number, so its four " +
      "spots land shifted and with no height (its tabs float alone). The app uses each box as given.",
    "S26 decision 7: a line counts as partly read when no product was identified or its current or poles were not " +
      "read. On the fixture that is RNV and C1–C4 (eight symbols), so the button counts 12 where the prototype's " +
      "hand-made list counts 4. A line's boxes on a page share one tab (C1–C4 on page 8).",
    "The tab sits on the box's inline-start corner in the drawing's own scale, as the prototype's 20px on its 1400px " +
      "canvas; the note is the tab's tooltip.",
  ];
  return [
    {
      id: "review-unresolved",
      title: 'Review: the "לא פוענח" layer (page 4)',
      prototype: { hash: "#review", authed: true, setup: protoPage(4) },
      app: { ...review, setup: appPage(4) },
      notes: layerNotes,
      window: true,
    },
    {
      id: "review-unresolved-p8",
      title: 'Review: the "לא פוענח" layer (page 8)',
      prototype: { hash: "#review", authed: true, setup: protoPage(8) },
      app: { ...review, setup: appPage(8) },
      notes: ["\"9 / 5\" by RNV's contact is the orphan text; RNV's own box there is the same place, drawn once."],
      window: true,
    },
    {
      id: "export-modal",
      title: "Review: הורדת ההצעה",
      prototype: { hash: "#review", authed: true, setup: (p) => p.locator('[data-act="export"]').click() },
      app: {
        ...review,
        setup: async (page) => {
          await appReview(page);
          await page.getByTestId("export").click();
          await page.getByTestId("export-row").first().waitFor();
        },
      },
      notes: [
        "The preview is the server's customer document, the PDF's own rows: Q0's kit part, included in its price, is " +
          'not a row. A draft says "טיוטה", as its PDF does on every page (S26 decision 3).',
        "The warning counts the rows with no price (5); the prototype counts red lines.",
        'A quote with more than one version gets a selector where "גרסה 1" is (S26 decision 2).',
        "Totals keep agorot (₪841.32), as on the review screen.",
      ],
    },
    {
      id: "prefs-document",
      title: 'Settings: "המסמך ללקוח" (no prototype screen; compared with settings)',
      prototype: { hash: "#prefs", authed: true },
      app: {
        path: "/prefs",
        tenant: TENANTS.s24Shots,
        setup: (page) => page.getByTestId("document-settings").getByLabel("שם המפעל").waitFor(),
      },
      notes: [
        "S26 decision 1: the logo, the factory's details, its terms and the SKU switch, for the customer PDF. Built " +
          "from the settings screen's card, row, field and switch classes, after the defaults, behind export_doc.",
        "The E2E tenant has written no template, so the name is its account name and the other fields are empty.",
      ],
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
