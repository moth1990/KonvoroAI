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

import { signIn, TENANTS } from "../fixtures";
import { prototypePort } from "./fidelity.config";

const OUT = fileURLToPath(new URL("./out/", import.meta.url));
const REPORT = fileURLToPath(new URL("./report.html", import.meta.url));
const PROTOTYPE = `http://127.0.0.1:${prototypePort}/konboro-app.html`;

interface Screen {
  id: string;
  title: string;
  prototype: { hash: string; authed: boolean; flags?: Record<string, boolean> };
  app: { path: string; tenant?: string };
  notes: string[];
}

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
];

const VIEWPORTS = [
  { id: "desktop", width: 1440, height: 900 },
  { id: "mobile", width: 375, height: 812 },
] as const;
const SCHEMES = ["light", "dark"] as const;

// Both apps scroll inside .main; let the page grow instead, so a full-page shot shows everything.
const UNROLL = `html,body,#root,#app{height:auto!important}
.shell{height:auto!important;min-height:100vh}.main{height:auto!important;overflow:visible!important}`;

async function shoot(page: Page, file: string) {
  await page.waitForLoadState("networkidle");
  if (await page.locator(".shell").count()) await page.addStyleTag({ content: UNROLL });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${OUT}${file}`, fullPage: true, animations: "disabled" });
}

/** Screenshots go inside the report, so it opens anywhere as one file. */
const inline = (file: string) => `data:image/png;base64,${readFileSync(`${OUT}${file}`).toString("base64")}`;

const shots: { screen: Screen; viewport: string; scheme: string; file: string }[] = [];

test.beforeAll(() => mkdirSync(OUT, { recursive: true }));

for (const screen of SCREENS) {
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
        await shoot(p, `${name}-prototype.png`);
        await proto.close();

        const app = await browser.newContext({ ...options, baseURL: test.info().project.use.baseURL });
        const a = await app.newPage();
        if (screen.app.tenant) await signIn(a, app.request, screen.app.tenant);
        await a.goto(screen.app.path);
        await shoot(a, `${name}-app.png`);
        await app.close();

        shots.push({ screen, viewport: viewport.id, scheme, file: name });
      });
    }
  }
}

test.afterAll(() => {
  const sections = SCREENS.map((screen) => {
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
  }).join("");
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
<h1>Prototype fidelity: login, shell, home</h1>
<p>Generated ${new Date().toISOString()} by <code>make fidelity</code>. Left: prototype/konboro-app.html. Right: the app on the E2E API.
Phone layout starts at 860px in the app (09 §5.2), 820px in the prototype.</p>
${sections}
</body></html>`,
  );
});
