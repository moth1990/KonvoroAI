/**
 * The new-quote screen's logic (01 §4.6, prototype `vNew`, `validateFile`, lines 754–869), kept out of the
 * components so it can be tested on its own.
 *
 * The browser checks what it can before uploading (size and type by extension, 01 §4.3 check 2); the server checks
 * again by content and counts pages, and its per-file answer replaces these.
 */
import type { Progress, UploadedFile } from "../../api/client";
import { countText } from "../../format";

export const MAX_FILE_MB = 20;
const ACCEPTED = ["pdf", "png", "jpg", "jpeg", "webp", "heic", "xlsx", "csv", "zip"];
const CAD = ["dwg", "dxf"];

/** 01 §8, the same texts the server sends. */
export const MESSAGES = {
  cad_not_supported: "קבצי DWG ו-DXF עדיין לא נתמכים. ייצאו PDF מתוכנת השרטוט (Plot ל-PDF) והעלו אותו.",
  unsupported_format: "סוג הקובץ לא נתמך. אפשר להעלות PDF, תמונה, אקסל או CSV.",
  too_large: (name: string) =>
    `הקובץ ${name} גדול מ-${MAX_FILE_MB}MB. אפשר לייצא אותו מחדש בלי תמונות ברזולוציה גבוהה, או לפצל אותו.`,
} as const;

export interface PickedFile {
  key: string;
  file: File;
  /** From the server once it has seen the file. */
  pages?: number | null;
  error?: { code: string; message: string } | null;
}

export function clientCheck(file: { name: string; size: number }): PickedFile["error"] {
  const ext = file.name.includes(".") ? (file.name.split(".").pop() ?? "").toLowerCase() : "";
  if (CAD.includes(ext)) return { code: "cad_not_supported", message: MESSAGES.cad_not_supported };
  if (!ACCEPTED.includes(ext)) return { code: "unsupported_format", message: MESSAGES.unsupported_format };
  if (file.size > MAX_FILE_MB * 1024 * 1024) return { code: "too_large", message: MESSAGES.too_large(file.name) };
  return null;
}

/** The server's per-file answer, matched to the picked files by name and order. */
export function applyServerCheck(files: PickedFile[], answer: UploadedFile[]): PickedFile[] {
  const left = [...answer];
  return files.map((f) => {
    const i = left.findIndex((a) => a.name === f.file.name || a.name.startsWith(`${f.file.name}/`));
    if (i < 0) return f;
    const mine = left.filter((a) => a.name === f.file.name || a.name.startsWith(`${f.file.name}/`));
    for (const m of mine) left.splice(left.indexOf(m), 1);
    const bad = mine.find((a) => a.error);
    const pages = mine.reduce((sum, a) => sum + (a.page_count ?? 0), 0);
    return {
      ...f,
      pages: pages || null,
      error: bad ? { code: bad.error ?? "", message: bad.message ?? MESSAGES.unsupported_format } : null,
    };
  });
}

/** "0.8MB", one decimal, as in the prototype's file rows. */
export function sizeText(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return `${mb < 0.1 ? 0.1 : Math.round(mb * 10) / 10}MB`;
}

export interface StartState {
  text: string;
  isError: boolean;
  canStart: boolean;
}

/** The start bar under the file list (01 §4.6 item 4, prototype lines 820–826). */
export function startState(o: {
  files: PickedFile[];
  revision: boolean;
  revisionOf: string;
  remaining: number | null;
  busy: boolean;
}): StartState {
  const bad = o.files.filter((f) => f.error).length;
  const ok = o.files.length - bad;
  if (bad) {
    const which = bad === 1 ? "קובץ אחד חורג. הסירו אותו" : `${bad} קבצים חורגים. הסירו אותם`;
    return { text: `${which} או החליפו, כדי שלא יחסר לוח בהצעה.`, isError: true, canStart: false };
  }
  const files = countText(ok, "קובץ אחד", (n) => `${n} קבצים`);
  if (o.revision) {
    if (!o.revisionOf) return { text: "בחרו למעלה את ההצעה הקיימת", isError: false, canStart: false };
    return { text: `${files} · גרסה חדשה, לא נספרת במכסה`, isError: false, canStart: ok > 0 && !o.busy };
  }
  if (o.remaining !== null && o.remaining <= 0)
    return { text: "המכסה החודשית מלאה. אפשר להעלות גרסה חדשה של שרטוט קיים", isError: true, canStart: false };
  const left = o.remaining === null ? "" : ` (נותרו ${o.remaining})`;
  return {
    text: `${files} · ייספר 1 מהמכסה${left} רק אם הקליטה מצליחה`,
    isError: false,
    canStart: ok > 0 && !o.busy,
  };
}

export type StageState = "done" | "run" | "wait" | "failed" | "skipped";

export interface StageRow {
  stage: number;
  name: string;
  state: StageState;
  summary: string | null;
}

/** The run step's 7 rows. While the drawing waits in the queue, its next stage already shows as working. */
export function stageRows(p: Progress): StageRow[] {
  const active = p.status === "uploaded" || p.status === "processing";
  const next = p.stages.find((s) => s.status !== "done")?.stage ?? null;
  return p.stages.map((s) => ({
    stage: s.stage,
    name: s.name,
    summary: s.summary ?? null,
    state:
      s.status === "done"
        ? "done"
        : s.status === "failed"
          ? "failed"
          : s.status === "skipped"
            ? "skipped"
            : active && (s.status === "running" || s.stage === next)
              ? "run"
              : "wait",
  }));
}

/** "שלב 3 מתוך 7": the stage being worked on, or the last one when finished. */
export function stageCounter(p: Progress): number {
  const done = p.stages.filter((s) => s.status === "done").length;
  return Math.min(done + 1, 7);
}

export const PAGE_KINDS: Record<string, string> = {
  single_line_diagram: "חד-קווי",
  control_diagram: "תוכנית פיקוד",
  panel_front_view: "חזית לוח",
  legend: "מקרא",
  bom_table: "כתב כמויות",
  general_notes: "הערות",
  technical_data: "נתונים טכניים",
  terminal_diagram: "תוכנית מהדקים",
  title_cover: "שער",
  factory_template: "תבנית מפעל",
  other: "אחר",
};

export const ROUTES: Record<string, { label: string; chip: string; note: string }> = {
  process: { label: "פענוח", chip: "acc", note: "נשלח לפענוח" },
  context: { label: "הקשר", chip: "out", note: "נקרא להקשר, לא נספר" },
  skip: { label: "דילוג", chip: "", note: "לא נקרא" },
};

type ProgressPage = Progress["pages"][number];

/** The line under each page card (prototype line 851): how the page was classified, and what happens to it. */
export function pageNote(page: ProgressPage): string {
  if (page.classified_by === "user") return "סווג על ידיכם";
  if (page.unsure) return "ביטחון נמוך. בדקו את הסוג"; // what the user must act on, even on a reused page
  if (page.classified_by === "template") return "זוהה לפי תבנית המפעל";
  if (page.classified_by === "reused") return "כמו בשרטוט שכבר פוענח";
  if (page.route === "context") return "נקרא להקשר, לא נספר";
  return "ביטחון גבוה";
}

/** Why stage 1 asks the user to look (01 §5.6), as the confirmation step says it. */
export const CONFIRM_REASONS: Record<string, string> = {
  low_confidence: "חלק מהעמודים סווגו בביטחון נמוך. הם מסומנים, ואפשר לשנות להם את הסוג.",
  no_diagram_pages: "לא מצאנו תוכנית חד-קווית. בדקו את הסיווג.",
  panel_count_mismatch: "מספר הלוחות שמצאנו שונה ממה שציינתם.",
  bom_mapping: "לא זיהינו בוודאות את העמודות בכתב הכמויות. בחרו איזו עמודה היא הפריט ואיזו הכמות.",
};

/** A BOM column's role, as the confirmation step names it (01 §5.8, S14). */
export const BOM_ROLES: Record<string, string> = {
  item: "פריט",
  quantity: "כמות",
  panel: "לוח",
  model: 'דגם / מק"ט',
  brand: "יצרן",
  unit: "יחידה",
  row_number: "מספר שורה",
  price: "מחיר (לא נקרא)",
  other: "לא בשימוש",
};

/** Who gave a column its role. */
export const BOM_BY: Record<string, { label: string; chip: string }> = {
  code: { label: "לפי הכותרת", chip: "" },
  model: { label: "הצעה, לבדיקה", chip: "warn" },
  user: { label: "נבחר על ידיכם", chip: "ok" },
};

/** The spreadsheet pages whose column mapping the confirmation step shows. */
export function bomPages(p: Progress): ProgressPage[] {
  return p.pages.filter((page) => page.bom?.source === "spreadsheet");
}

/** Why "אשר והמשך" waits, or null: every BOM table needs one item column and one quantity column. */
export function bomProblem(p: Progress): string | null {
  for (const page of bomPages(p)) {
    const roles = page.bom?.columns.map((c) => c.role) ?? [];
    const items = roles.filter((r) => r === "item").length;
    const quantities = roles.filter((r) => r === "quantity").length;
    const sheet = page.bom?.sheet ? ` בגיליון "${page.bom.sheet}"` : "";
    if (items !== 1 || quantities !== 1) return `בחרו עמודת פריט אחת ועמודת כמות אחת${sheet}.`;
  }
  return null;
}

/** The line above the page grid on the done step (prototype line 846). */
export function gridHint(p: Progress): string {
  const low = p.pages.some((page) => page.unsure);
  return low
    ? "חלק מהעמודים סווגו בביטחון נמוך. אפשר לשנות סוג עמוד כאן או ממסך הבדיקה."
    : "כל העמודים סווגו בביטחון גבוה. אפשר לשנות סוג עמוד כאן או ממסך הבדיקה.";
}

/** The quota line at the bottom of the done step. */
export function countedText(p: Progress, quotaLabel: string): string {
  if (p.counted_as === "revision") return "גרסה חדשה של הצעה קיימת. לא נספרה במכסה.";
  if (p.counted_as === "reuse") return "אותם קבצים כבר פוענחו. לא נספרה במכסה.";
  return `נספרה במכסה: ${quotaLabel}`;
}

export const INPUT_KINDS: Record<string, [string, string]> = {
  factory_drawing: ["שרטוט ייצור", "של מפעל לוחות"],
  designer_plan: ["תוכנית מתכנן", "של מתכנן חשמל"],
  bom_only: ["כתב כמויות", "בלי שרטוט"],
  mixed: ["שרטוט וכתב כמויות", "כתב הכמויות להשוואה"],
};
