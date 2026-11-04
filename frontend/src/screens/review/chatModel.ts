/**
 * The chat drawer's pure parts (08 §8.1, prototype `vChat`, `propCard`): a text block's references, the amounts of
 * its money references, a proposal card's rows, warnings and totals, and the greeting. Amounts are always the
 * server's: the screen formats them, it never adds them up (09 principle 7).
 */
import type { ChatMoney, ChatProposal, Quote, QuoteLine } from "../../api/client";
import { percent, shekels } from "./model";

/** The review screen's suggestions under the conversation (09 §6.7; prototype `SUGG`). The prototype's fourth,
 * closing a finding, is not one of 08 §6.7's changes; showing the red lines is (S25 decision 6). */
export const SUGGESTIONS = [
  "למה המגענים צהובים?",
  "מה חסר כדי לשלוח?",
  'החלף את כל מא"זי ABB ל-Schneider',
  "תראה לי את השורות האדומות",
];

export type Segment =
  | { kind: "text"; text: string }
  | { kind: "line"; lineId: string }
  | { kind: "money"; ref: string }
  | { kind: "quote"; quoteId: string }
  | { kind: "instance"; instanceId: string };

const REF = /\{\{\s*(line:ln_[0-9A-Z]+|quote:quo_[0-9A-Z]+|instance:[^\s{}]+|\$[A-Z]\d+)\s*\}\}/g;

function segment(ref: string): Segment {
  if (ref.startsWith("line:")) return { kind: "line", lineId: ref.slice(5) };
  if (ref.startsWith("quote:")) return { kind: "quote", quoteId: ref.slice(6) };
  if (ref.startsWith("instance:")) return { kind: "instance", instanceId: ref.slice(9) };
  return { kind: "money", ref };
}

/** A text block's content as text, line chips, amounts, other quotes' names and the drawing's instances (S25b). */
export function segments(content: string): Segment[] {
  const out: Segment[] = [];
  let at = 0;
  for (const m of content.matchAll(REF)) {
    if (m.index > at) out.push({ kind: "text", text: content.slice(at, m.index) });
    out.push(segment(m[1] ?? ""));
    at = m.index + m[0].length;
  }
  if (at < content.length) out.push({ kind: "text", text: content.slice(at) });
  return out;
}

/** An option's text as its chip shows it: a quote by its name (the model only knew it as QT2, S25b decision 1). */
export function optionLabel(option: string, quotes: Record<string, string | undefined>): string {
  return segments(option)
    .map((s) => (s.kind === "text" ? s.text : s.kind === "quote" ? (quotes[s.quoteId] ?? "הצעה אחרת") : ""))
    .join("")
    .trim();
}

/** A money reference as the screen shows it; "—" when the server sent no amount for it. */
export function amount(money: Record<string, ChatMoney | undefined>, ref: string | null | undefined): string {
  if (!ref) return "—";
  const m = money[ref];
  if (!m) return "—";
  return m.kind === "pct" ? percent(m.value) : shekels(m.value);
}

/** A line chip's text: its designators when it has them, else its description, short. */
export function lineLabel(line: QuoteLine | undefined): string {
  if (!line) return "שורה";
  if (line.designators.length)
    return line.designators.slice(0, 3).join(", ") + (line.designators.length > 3 ? "…" : "");
  return line.description.length > 28 ? `${line.description.slice(0, 27)}…` : line.description;
}

type Side = {
  sku?: string | null;
  manufacturer?: string | null;
  description?: string | null;
  qty?: string | null;
  unit_price?: string | null;
};

function sideText(s: Side, money: Record<string, ChatMoney | undefined>, withPrice: boolean): string {
  const name = s.description ?? [s.manufacturer, s.sku].filter(Boolean).join(" ");
  const qty = s.qty && Number(s.qty) !== 1 ? ` ×${Number(s.qty)}` : "";
  return withPrice ? `${name}${qty} · ${amount(money, s.unit_price)}` : `${name}${qty}`;
}

export type DiffRow = { lineId: string | null; before: string; after: string; note: string | null };

type Diff = {
  lines_changed: { line_id: string; before: Side; after: Side; note: string | null }[];
  lines_added: { line_id: string; after: Side; restored?: boolean }[];
  lines_removed: { line_id: string; before: Side }[];
  derived_changes?: { line_id: string; before: Side; after: Side; note: string | null }[];
};

const same = (a: Side, b: Side) => JSON.stringify(a) === JSON.stringify(b);

/** The card's before → after rows (prototype `propCard`'s `.diff`): only the lines that change. */
export function diffRows(p: ChatProposal): DiffRow[] {
  const d = p.diff as Diff;
  const rows: DiffRow[] = [];
  for (const x of [...d.lines_changed, ...(d.derived_changes ?? [])]) {
    if (same(x.before, x.after)) continue;
    const priceOnly =
      x.before.sku === x.after.sku && x.before.qty === x.after.qty && x.before.description === x.after.description;
    rows.push({
      lineId: x.line_id,
      before: sideText(x.before, p.money, priceOnly),
      after: sideText(x.after, p.money, priceOnly),
      note: x.note,
    });
  }
  for (const x of d.lines_added)
    rows.push({
      lineId: x.line_id,
      before: x.restored ? "הוסר" : "—",
      after: sideText(x.after, p.money, false),
      note: null,
    });
  for (const x of d.lines_removed)
    rows.push({ lineId: x.line_id, before: sideText(x.before, p.money, false), after: "נמחק", note: null });
  return rows;
}

/** Lines the change asked for that stay as they are, one sentence per reason ("3 שורות לא משתנות: …"). */
export function unchanged(p: ChatProposal): string[] {
  const by = new Map<string, number>();
  for (const x of (p.diff as Diff).lines_changed)
    if (same(x.before, x.after) && x.note) by.set(x.note, (by.get(x.note) ?? 0) + 1);
  return [...by].map(([note, n]) => `${n === 1 ? "שורה אחת לא משתנה" : `${n} שורות לא משתנות`}: ${note}`);
}

const WARNINGS: Record<string, (p: ChatProposal) => string> = {
  partial_brand_coverage: () => "חלק מהשורות לא מתחלפות: אין להן מוצר מתאים במותג החדש",
  sku_attribute_mismatch: () => 'התכונות של המק"ט החדש שונות מאלה שבשרטוט',
  not_applied: () => "חלק מהשורות לא משתנות כמו שביקשת. הסיבה ליד כל שורה",
  many_lines: (p) => `השינוי משפיע על ${p.affected_line_count} שורות`,
  many_deletes: (p) => `${deletedCount(p)} שורות יימחקו`,
  new_issues: (p) => `ממצאים חדשים מהבודק: ${(p.diff as { new_issues: string[] }).new_issues.join(" · ")}`,
  opens_new_version: (p) => `ההצעה נשלחה. האישור יפתח גרסה ${p.base_version + 1}`,
};

/** The card's warnings. The lines left as they are already say why (`unchanged`), so their general warning goes. */
export function warningTexts(p: ChatProposal): string[] {
  const told = unchanged(p).length > 0;
  return p.warnings
    .filter((w) => !(told && (w === "partial_brand_coverage" || w === "not_applied")))
    .map((w) => WARNINGS[w]?.(p))
    .filter((t): t is string => !!t);
}

export function deletedCount(p: ChatProposal): number {
  return Number((p.diff as { deleted_count?: number }).deleted_count ?? 0);
}

export type Remember = "quote_only" | "customer" | "tenant";

/** 08 §7.3–7.4, S25b decision 2: the card's memory chips, "רק בהצעה הזו" first and selected by default. */
export const REMEMBER: Record<Remember, string> = {
  quote_only: "רק בהצעה הזו",
  customer: "לזכור ללקוח הזה",
  tenant: "לזכור למפעל",
};

/** The chips a proposal offers; none when it offers only this quote (prices, margins, quantities). */
export function rememberChoices(p: ChatProposal): Remember[] {
  const offered = p.remember_options ?? ["quote_only"];
  return offered.length > 1 ? (["quote_only", "customer", "tenant"] as const).filter((r) => offered.includes(r)) : [];
}

/** An applied card's note when it was remembered. */
export function rememberedText(p: ChatProposal): string | null {
  if (p.remembered === "customer") return "נשמר בזיכרון ההתאמות של הלקוח";
  if (p.remembered === "tenant") return "נשמר בזיכרון ההתאמות של המפעל";
  return null;
}

/** 08 §9: deleting more than 5 lines says so on the button. */
export function applyLabel(p: ChatProposal): string {
  return p.warnings.includes("many_deletes") ? `מחק ${deletedCount(p)} שורות` : "החל";
}

export function totals(p: ChatProposal): { before: string; after: string } | null {
  const d = p.diff as { totals_before?: { net_total?: string | null }; totals_after?: { net_total?: string | null } };
  if (!d.totals_before?.net_total && !d.totals_after?.net_total) return null;
  return { before: amount(p.money, d.totals_before?.net_total), after: amount(p.money, d.totals_after?.net_total) };
}

export const STATE: Record<ChatProposal["status"], { text: string; tone: string }> = {
  pending: { text: "ממתין לאישור", tone: "acc" },
  applied: { text: "הוחל", tone: "ok" },
  dismissed: { text: "בוטל", tone: "" },
  expired: { text: "פג תוקף", tone: "warn" },
  undone: { text: "בוטל אחרי שהוחל", tone: "" },
};

/** The first message, from the quote, with no model (prototype `msgs[0]`). */
export function greeting(q: Quote): string {
  const lines = q.panels.flatMap((p) => p.lines).filter((l) => l.line_type !== "derived" && l.line_type !== "labor");
  const priced = lines.filter((l) => l.unit_price != null).length;
  const missing = lines.length - priced;
  const f = q.findings.length;
  let text = `הפענוח של ${q.name} הסתיים: ${lines.length} מוצרים, ${priced} עם מחיר מהמחירון שלך.`;
  if (missing)
    text += ` ${missing === 1 ? "חסר מחיר לשורה אחת" : `חסרים מחירים ל-${missing} שורות`}${f ? `, ויש ${f} ממצאים.` : "."}`;
  else if (f) text += ` יש ${f} ממצאים.`;
  return `${text} מה לבדוק קודם?`;
}
