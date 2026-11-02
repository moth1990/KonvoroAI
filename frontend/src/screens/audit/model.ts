/**
 * The audit screen's logic (11 §5.4–7, prototype `vAudit`; S16 decision 1): the headline, the KPIs, how the
 * differences are grouped, and how each row reads. Money arrives as decimal strings and is only formatted, never
 * added up here: the server's summary has the sums (CLAUDE.md non-negotiable 5).
 */
import type { Audit, AuditDifference, AuditLine, QuotePage, RejectReason } from "../../api/client";
import { countText } from "../../format";
import { clientCheck, type PickedFile } from "../newQuote/model";
import { shekels } from "../review/model";

export type DifferenceType = AuditDifference["type"];

/** A missing item and a short quantity are omissions (S16 decision 3, as the prototype counts 10271's three). */
export const OMISSIONS: DifferenceType[] = ["missing_in_quote", "qty_short"];
/** Shown for information: never counted, no decision, no money (11 §5.4). */
export const INFO_TYPES: DifferenceType[] = ["not_a_difference", "drawing_conflict"];

/** The chip under each difference's name (prototype: "כמות", "חסר", "חומר עזר"). */
export const TYPE_CHIPS: Record<DifferenceType, [string, "bad" | "warn" | "acc" | ""]> = {
  missing_in_quote: ["חסר", "bad"],
  qty_short: ["כמות", "bad"],
  attribute_mismatch: ["תכונה שונה", "bad"],
  arithmetic: ["חשבון", "bad"],
  possible_double_count: ["ספירה כפולה", "warn"],
  qty_over: ["כמות עודפת", "warn"],
  extra_in_quote: ["אין בשרטוט", "warn"],
  drawing_conflict: ["סתירה בשרטוט", "acc"],
  not_a_difference: ["חומר עזר", ""],
};

/** "לא נכון" and why (11 §7; S15 stores them for the learning loop, 11 §9). */
export const REJECT_REASONS: [RejectReason, string][] = [
  ["included_elsewhere", "כלול במחיר אחר"],
  ["customer_supplies", "הלקוח מספק"],
  ["system_error", "טעות של המערכת"],
  ["other", "אחר"],
];

export interface Groups {
  /** Confidence 0.6 and up, counted: the differences table. */
  shown: AuditDifference[];
  /** Not a difference, or a conflict the quote settles: at the end of the same table, as the prototype does. */
  info: AuditDifference[];
  /** Below 0.6, of any type: "לבדוק, ייתכן שזו טעות של המערכת" (11 §5.4). */
  toCheck: AuditDifference[];
}

/** The server's order is kept within each group (missing first, then by confidence). */
export function groups(diffs: AuditDifference[]): Groups {
  const out: Groups = { shown: [], info: [], toCheck: [] };
  for (const d of diffs) {
    if (!d.shown) out.toCheck.push(d);
    else if (INFO_TYPES.includes(d.type)) out.info.push(d);
    else out.shown.push(d);
  }
  return out;
}

/** "2.000" → 2. Quantities are whole units here; a part of one rounds down, as the audit counts them. */
function whole(v: string | null | undefined): number {
  if (v == null) return 0;
  return Number.parseInt(v.split(".")[0] ?? "0", 10) || 0;
}

/** Units the quote leaves out: a missing item's drawn quantity, or how many a short line lacks. */
export function shortUnits(d: AuditDifference): number {
  if (d.type === "missing_in_quote") return whole(d.drawing_qty);
  if (d.type === "qty_short") return Math.max(whole(d.drawing_qty) - whole(d.quote_qty), 0);
  return 0;
}

function isZero(amount: string | null | undefined): boolean {
  return amount == null || !/[1-9]/.test(amount);
}

export interface Kpis {
  matched: string;
  omissions: number;
  units: number;
  atRisk: string;
  /** Some omissions have no price: the amount is "at least" (prototype "₪1,250+"). */
  unpriced: number;
  notDifferences: number;
}

export function kpis(audit: Audit): Kpis {
  const g = groups(audit.differences);
  const omissions = g.shown.filter((d) => OMISSIONS.includes(d.type));
  const s = audit.summary;
  return {
    matched: s ? `${s.lines_matched} / ${s.quote_lines}` : "—",
    omissions: omissions.length,
    units: omissions.reduce((n, d) => n + shortUnits(d), 0),
    atRisk: shekels(s?.value_at_risk ?? "0"),
    unpriced: omissions.filter((d) => d.amount == null).reduce((n, d) => n + shortUnits(d), 0),
    notDifferences: g.info.filter((d) => d.type === "not_a_difference").length,
  };
}

/** Hebrew "and" before the last item: "ורכיב", "ו-12". */
function joinAnd(parts: string[]): string {
  if (parts.length < 2) return parts.join("");
  const last = parts[parts.length - 1] ?? "";
  return `${parts.slice(0, -1).join(", ")}, ${/^\d/.test(last) ? "ו-" : "ו"}${last}`;
}

/**
 * 11 §7's heading: "נמצאו 5 הבדלים: 12 רכיבים חסרים, ורכיב אחד שנספר פעמיים. כסף בסיכון: ₪140, ועוד 11 רכיבים
 * בלי מחיר." Only the differences shown count; the ones to check are said apart.
 */
export function headline(audit: Audit): string {
  const g = groups(audit.differences);
  const k = kpis(audit);
  const s = audit.summary;
  const check = g.toCheck.length ? ` ${countText(g.toCheck.length, "הבדל אחד", (n) => `${n} הבדלים`)} לבדוק.` : "";
  if (!g.shown.length) return `לא נמצאו הבדלים בין ההצעה לשרטוט.${check}`;

  const parts: string[] = [];
  if (k.units) parts.push(countText(k.units, "רכיב אחד חסר", (n) => `${n} רכיבים חסרים`));
  const doubles = g.shown.filter((d) => d.type === "possible_double_count").length;
  if (doubles) parts.push(countText(doubles, "רכיב אחד שנספר פעמיים", (n) => `${n} רכיבים שנספרו פעמיים`));
  const other = g.shown.filter((d) => !OMISSIONS.includes(d.type) && d.type !== "possible_double_count").length;
  if (other) parts.push(countText(other, "הבדל אחר", (n) => `${n} הבדלים אחרים`));

  const found = countText(g.shown.length, "נמצא הבדל אחד", (n) => `נמצאו ${n} הבדלים`);
  let text = `${found}: ${joinAnd(parts)}.`;
  const unpriced = countText(k.unpriced, "רכיב אחד", (n) => `${n} רכיבים`);
  if (!isZero(s?.value_at_risk)) {
    text += ` כסף בסיכון: ${k.atRisk}`;
    text += k.unpriced ? `, ועוד ${unpriced} בלי מחיר.` : ".";
  } else if (k.unpriced) text += ` ל-${unpriced} אין מחיר דומה בהצעה.`;
  if (!isZero(s?.over_charged)) text += ` נגבה ביותר: ${shekels(s?.over_charged)}.`;
  return text + check;
}

/**
 * The row's name: the product to add or fix, else the quote's own line, else the head of the message without its
 * count and tags ("מהדק × 16 (C, COM): חומר עזר…" → "מהדק"; the tags are in the evidence column).
 */
export function title(d: AuditDifference, lines: AuditLine[]): string {
  if (d.suggested_line) return d.suggested_line.description;
  const line = lines.find((ln) => ln.index === d.quote_line_index);
  if (line) return line.description;
  const head = d.message.split(":")[0] ?? d.message;
  return (
    head
      .replace(/\s*\([^)]*\)\s*$/, "")
      .replace(/\s*×\s*\d+$/, "")
      .trim() || d.message
  );
}

/** "2.000" → "2"; none or 0 → "—" (prototype: a missing item has "—" in the quote's column). */
export function qtyText(v: string | null | undefined): string {
  if (v == null || isZero(v)) return "—";
  const [w = "0", f = ""] = v.split(".");
  const frac = f.replace(/0+$/, "");
  return frac ? `${w}.${frac}` : w;
}

/** The money column: at risk, over-charged, or why there is none. */
export function moneyText(d: AuditDifference): { text: string; muted: boolean } {
  if (d.amount != null && !isZero(d.amount)) {
    if (d.amount.startsWith("-")) return { text: `נגבה ביותר ${shekels(d.amount.slice(1))}`, muted: false };
    return { text: shekels(d.amount), muted: false };
  }
  if (OMISSIONS.includes(d.type) || d.type === "attribute_mismatch") return { text: "אין מחיר דומה", muted: true };
  return { text: "—", muted: true };
}

/** "עמוד 3", "עמודים 3, 5", or the quote's line when the drawing has nothing ("שורה 13 בהצעה"). */
export function whereText(d: AuditDifference): string {
  const pages = [...new Set(d.evidence.map((e) => e.page_no))].sort((a, b) => a - b);
  if (pages.length === 1) return `עמוד ${pages[0]}`;
  if (pages.length > 1) return `עמודים ${pages.join(", ")}`;
  if (d.quote_line_index != null) return `שורה ${d.quote_line_index} בהצעה`;
  return "";
}

export function decidable(d: AuditDifference): boolean {
  return !INFO_TYPES.includes(d.type);
}

export function decisionText(d: AuditDifference): string | null {
  if (d.status === "confirmed") return "אושר";
  if (d.status === "rejected") {
    const reason = REJECT_REASONS.find(([k]) => k === d.reject_reason)?.[1] ?? "";
    return reason ? `נדחה: ${reason}` : "נדחה";
  }
  return null;
}

/** "שתי שורות בהצעה מכסות כמה מכשירים": a line that names what it includes (11 §5.2 item 6). */
export function coversSeveral(line: AuditLine): boolean {
  return line.includes.length > 0 || /כולל|\+/.test(line.description);
}

export function matchedLines(audit: Audit): AuditLine[] {
  return audit.lines.filter((ln) => ln.status === "matched");
}

/** "נוצרה טיוטה מתוקנת: 17 שורות + 3 חסרות" (prototype toast): the quote's lines and the confirmed omissions. */
export function correctedText(audit: Audit): string {
  const added = audit.differences.filter((d) => d.status === "confirmed" && OMISSIONS.includes(d.type)).length;
  const lines = countText(audit.lines.length, "שורה אחת", (n) => `${n} שורות`);
  return `נוצרה טיוטה מתוקנת: ${lines}${added ? ` + ${countText(added, "חסרה אחת", (n) => `${n} חסרות`)}` : ""}`;
}

/** The page "הצג בשרטוט" opens first: the first page the difference is boxed on. */
export function firstBoxPage(d: AuditDifference, pages: QuotePage[]): string | null {
  const order = new Map(pages.map((p) => [p.page_id, p.page_no]));
  const boxed = [...d.boxes].sort((a, b) => (order.get(a.page_id) ?? 0) - (order.get(b.page_id) ?? 0));
  return boxed[0]?.page_id ?? null;
}

/** 01 §8 / the server's `quote_not_one_file`: the existing quote is one file, never a ZIP (S15). */
export const QUOTE_NOT_ONE_FILE = "את ההצעה הקיימת מעלים כקובץ אחד: PDF, תמונה, אקסל או CSV.";

export function quoteCheck(file: { name: string; size: number }): PickedFile["error"] {
  if (/\.zip$/i.test(file.name)) return { code: "quote_not_one_file", message: QUOTE_NOT_ONE_FILE };
  return clientCheck(file);
}

/** The audit's start bar: both sides are needed, and an audit counts only once stage 1 succeeds (11 §4). */
export function auditStartState(o: {
  drawings: PickedFile[];
  quote: PickedFile | null;
  remaining: number | null;
  busy: boolean;
}): { text: string; isError: boolean; canStart: boolean } {
  const bad = [...o.drawings, ...(o.quote ? [o.quote] : [])].filter((f) => f.error).length;
  if (bad) return { text: "יש קובץ שנדחה. הסירו אותו או החליפו", isError: true, canStart: false };
  if (!o.drawings.length) return { text: "בחרו את השרטוט", isError: false, canStart: false };
  if (!o.quote) return { text: "בחרו את ההצעה הקיימת", isError: false, canStart: false };
  if (o.remaining !== null && o.remaining <= 0) return { text: "המכסה החודשית מלאה", isError: true, canStart: false };
  const left = o.remaining === null ? "" : ` (נותרו ${o.remaining})`;
  return { text: `ייספר 1 מהמכסה${left} רק אם הקליטה מצליחה`, isError: false, canStart: !o.busy };
}
