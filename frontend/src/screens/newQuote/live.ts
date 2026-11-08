/**
 * The live run step's logic (01 §4.6, 13 §4.11 `live_run`; prototype `updateRun`, `estimate`, lines 836–1064),
 * kept out of the components so it can be tested on its own.
 *
 * Money arrives as a string (CLAUDE.md non-negotiable 5); it is only formatted here, never added up.
 */
import type { Estimate, Live, Progress } from "../../api/client";
import type { IconName } from "../../ui/Icon";
import type { PickedFile } from "./model";

/** Polled every two seconds with `live_run` (01 §4.6); the clock ticks in the browser between polls. */
export const LIVE_POLL_MS = 2000;

/** Each stage's icon (01 §4.6 table): the sparkle marks the ones a model can work in, 1–6 and the audit step. */
export const STAGE_ICONS: Record<number, IconName> = {
  1: "s_intake",
  2: "s_ocr",
  3: "s_detect",
  4: "s_graph",
  5: "s_match",
  6: "s_check",
  7: "s_price",
  8: "s_audit",
};

/** "$0.44", to the cent, from the API's string. */
export function usd(value: string | null | undefined): string {
  const n = Number(value ?? 0);
  return `$${(Number.isFinite(n) ? n : 0).toFixed(2)}`;
}

/** "2:05" */
export function mmss(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The start bar's "כ-3 דקות" (prototype `aboutMin`). */
export function aboutMin(seconds: number): string {
  if (seconds < 60) return "פחות מדקה";
  const minutes = Math.round(seconds / 60);
  return minutes === 1 ? "כדקה" : `כ-${minutes} דקות`;
}

/** "נותרו כ-2:30"; under 20 seconds, "כמה שניות"; before any stage ran, the whole run expected. */
export function leftText(live: Live): string {
  if (live.seconds_left === null) return "";
  if (live.elapsed_s < 4) return `צפוי כ-${mmss(Math.round(live.seconds_expected / 10) * 10)}`;
  return live.seconds_left < 20 ? "נותרו כמה שניות" : `נותרו כ-${mmss(live.seconds_left)}`;
}

/** "9 עמודים · כ-3 דקות · כ-$0.44" */
export function estimateText(e: Estimate): string {
  const pages = e.pages === 1 ? "עמוד אחד" : `${e.pages} עמודים`;
  return `${pages} · ${aboutMin(e.seconds)} · כ-${usd(e.cost_usd)}`;
}

/** The estimate is shown only when every valid file's pages are known and none is rejected (01 §4.6 item 4). */
export function shownEstimate(files: PickedFile[], estimate: Estimate | null): Estimate | null {
  if (!estimate || files.length === 0) return null;
  if (files.some((f) => f.error)) return null;
  return files.every((f) => f.pages) ? estimate : null;
}

/** The current stage: the one running, or the next one waiting while the drawing waits in the queue. */
export function currentStage(p: Progress): Progress["stages"][number] | undefined {
  return p.stages.find((s) => s.status === "running") ?? p.stages.find((s) => s.status === "queued");
}

/** The header's live sentence: "זיהוי הרכיבים: עמוד 5: 18 רכיבים" (01 §4.6). */
export function liveSentence(p: Progress): string {
  const stage = currentStage(p);
  if (!stage || !p.live) return "";
  const said = [...p.live.messages].reverse().find((m) => m.stage === stage.stage);
  return said ? `${stage.name}: ${said.text}` : stage.name;
}

/** The live message under the running stage. */
export function stageMessage(p: Progress, stage: number): string | null {
  const said = [...(p.live?.messages ?? [])].reverse().find((m) => m.stage === stage);
  return said?.text ?? null;
}

/** "שלב 3 מתוך 7": the stage being worked on, or "מסיים" once every one is done. */
export function stepText(p: Progress): string {
  const stage = currentStage(p);
  if (!stage) return "מסיים";
  return `שלב ${p.stages.indexOf(stage) + 1} מתוך ${p.stages.length}`;
}

const COUNTERS: [string, string][] = [
  ["pages", "עמודים"],
  ["tiles", "אריחים"],
  ["components", "רכיבים"],
  ["products", "מוצרים"],
  ["findings", "ממצאים"],
];

/** The counters under the page view: "עמודים 3/9", "אריחים 58"… (prototype `run-counters`). */
export function counterItems(counters: Record<string, number>, filePages = 0): { label: string; value: string }[] {
  const pages = counters.pages ?? filePages; // before stage 1 reports, the pages the upload counted
  return COUNTERS.map(([key, label]) => {
    const value = key === "pages" && pages ? `${counters.pages_read ?? 0}/${pages}` : String(counters[key] ?? 0);
    return { label, value };
  });
}

/** A box in PDF points as percentages of the page, from the inline start (the right, in RTL): the page is not
 * mirrored, so a box `x1` from the left is `100 − x1` from the right. */
export function boxStyle(box: number[], size: number[]): Record<string, string> {
  const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = box;
  const [w = 1, h = 1] = size;
  const pct = (v: number) => `${(100 * v).toFixed(2)}%`;
  return {
    insetInlineStart: pct((w - x1) / w),
    top: pct(y0 / h),
    width: pct((x1 - x0) / w),
    height: pct((y1 - y0) / h),
  };
}

/** The breakdown's "מה רץ": "Haiku × 4 · קריאת טקסט × 58"; pricing is "קוד בלבד" (07), and a stage that could call a
 * model and did not, "בלי מודל". */
export function modelsText(models: { label: string; calls: number }[], stage: number): string {
  if (models.length) return models.map((m) => `${m.label} × ${m.calls}`).join(" · ");
  return stage === 7 ? "קוד בלבד" : "בלי מודל";
}

/** The tab's title once a run is ready while the tab is hidden (01 §4.6). */
export const READY_TITLE = "✓ מוכן · ";

export function readyTitle(base: string): string {
  return base.startsWith(READY_TITLE) ? base : `${READY_TITLE}${base}`;
}

/** Wraps an amount in Unicode isolates, for plain-text toasts in an RTL page ("עלות עד כה: $0.12"). */
export function isolate(text: string): string {
  return `⁦${text}⁩`;
}

/** The end of a run while the tab is hidden (01 §4.6): the title says "✓ מוכן" until the user comes back, and with
 * "הודע לי" on and the browser's permission, a notification. Returns whether the title changed. */
export function announceHidden(text: string, notify: boolean, doc: Document = document): boolean {
  if (!doc.hidden) return false;
  const base = doc.title;
  doc.title = readyTitle(base);
  doc.addEventListener(
    "visibilitychange",
    () => {
      doc.title = base;
    },
    { once: true },
  );
  if (notify && typeof Notification !== "undefined" && Notification.permission === "granted")
    new Notification("קונבורו", { body: text });
  return true;
}

/** The toast on another screen when a run ends (prototype `runFinished`). */
export function finishedText(kind: "quote" | "audit", p: Progress): string {
  if (kind === "audit")
    return p.status === "failed" ? `הבדיקה של ${p.name} נכשלה` : `הבדיקה של ${p.name} הסתיימה. התוצאות ← בדיקת הצעה`;
  if (p.status === "failed") return `הפענוח של ${p.name} נכשל. הפרטים ← הצעה חדשה`;
  const products = p.summary ? (p.summary.products === 1 ? ": מוצר אחד" : `: ${p.summary.products} מוצרים`) : "";
  return `הפענוח של ${p.name} הסתיים${products}. לבדיקה ← הצעה חדשה`;
}

/** "שבעה שלבים", or the audit's "חמישה שלבים". */
export function stagesTitle(n: number): string {
  return n === 5 ? "חמישה שלבים" : n === 7 ? "שבעה שלבים" : `${n} שלבים`;
}
