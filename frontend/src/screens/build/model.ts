/**
 * The chat builder's screen model (13 §4.2, S27; prototype `vBuild`, `buildSay`, lines 1309–1357): the draft's rows,
 * what a message was understood as, and the counts under the table. Pure, for Vitest.
 */
import type { Build, BuildMessage, Quote, QuoteLine } from "../../api/client";
import { priceChips, qtyText, reasonChips, shekels, type Tone } from "../review/model";

export interface DraftRow {
  line: QuoteLine;
  panel: string | null; // shown when the draft has more than one panel
  chips: { text: string; tone: Tone }[];
  priced: boolean;
}

/** The lines the estimator described (component and manual lines), in the review's order, with their chips. */
export function draftRows(quote: Quote | null | undefined): DraftRow[] {
  if (!quote) return [];
  const several = quote.panels.length > 1;
  return quote.panels.flatMap((p) =>
    p.lines
      .filter(
        (ln) => ln.section === "items" && !ln.included && (ln.line_type === "component" || ln.line_type === "manual"),
      )
      .map((line) => ({
        line,
        panel: several ? p.name : null,
        chips: [...reasonChips(line, quote.findings), ...priceChips(line, quote.status === "sent")],
        priced: line.unit_price != null,
      })),
  );
}

/** Accessories, enclosure and labor stage 7 adds to every BOM (01 §5.8 "מה חסר"): one summary row. */
export function extras(quote: Quote | null | undefined): { count: number; total: string | null } {
  if (!quote) return { count: 0, total: null };
  const lines = quote.panels.flatMap((p) => p.lines).filter((ln) => ln.section === "extras" && !ln.included);
  if (!lines.length) return { count: 0, total: null };
  let agorot = 0n;
  let any = false;
  for (const ln of lines) {
    if (ln.line_total == null) continue;
    any = true;
    const [w = "0", f = ""] = ln.line_total.replace("-", "").split(".");
    const value = BigInt(w) * 100n + BigInt((f + "00").slice(0, 2));
    agorot += ln.line_total.startsWith("-") ? -value : value;
  }
  const sign = agorot < 0n ? "-" : "";
  const abs = agorot < 0n ? -agorot : agorot;
  return {
    count: lines.length,
    total: any ? `${sign}${abs / 100n}.${(abs % 100n).toString().padStart(2, "0")}` : null,
  };
}

/** "3 שורות · 1 בלי מחיר" (prototype line 1348). */
export function draftCounts(rows: DraftRow[]): string {
  const n = rows.length;
  const missing = rows.filter((r) => !r.priced).length;
  const lines = n === 1 ? "שורה אחת" : `${n} שורות`;
  return missing ? `${lines} · ${missing} בלי מחיר` : lines;
}

export function draftTotal(quote: Quote | null | undefined): string {
  return shekels(quote?.totals.net_total ?? "0");
}

/** What a message was understood as, one line each, for a recording's card (S27 decision 1). */
export function understood(m: BuildMessage): string[] {
  const out: string[] = [];
  for (const it of m.items)
    out.push(`${it.quantity > 1 ? `${it.quantity} × ` : ""}${it.text}${it.panel ? ` (${it.panel})` : ""}`);
  for (const ch of m.changes) {
    if (ch.action === "remove") out.push(`להסיר: ${ch.description}`);
    else if (ch.action === "set_qty") out.push(`${ch.description}: כמות ${ch.quantity}`);
    else out.push(`${ch.description}: עוד ${ch.quantity}`);
  }
  return out;
}

const DROPPED: Record<BuildMessage["dropped"][number]["reason"], string> = {
  not_in_message: "לא נמצא בהודעה",
  number_not_said: "יש בו ערך שלא נאמר",
  unknown_line: "לא נמצאה השורה בטיוטה",
  bad_quantity: "הכמות לא ברורה",
};

export function droppedText(m: BuildMessage): string[] {
  return m.dropped.map((d) => `"${d.quote}": ${DROPPED[d.reason]}`);
}

/** The recording waiting for "הוסף" or "תקן", if any. */
export function pending(build: Build | null | undefined): BuildMessage | null {
  return build?.messages.find((m) => m.role === "user" && m.status === "pending") ?? null;
}

/** The messages shown: everything but a recording that was dismissed with "תקן" (its text went back to the input). */
export function shownMessages(build: Build | null | undefined): BuildMessage[] {
  return (build?.messages ?? []).filter((m) => m.status !== "dismissed");
}

export function qtyOf(line: QuoteLine): string {
  return qtyText(line.qty);
}

export const INTRO_TEXT = "תארו את הלוח: מפסק ראשי, יציאות, פחת, מגענים, ארון. אפשר בכמה הודעות.";
export const EMPTY_DRAFT = "השורות יופיעו כאן תוך כדי השיחה. כל שורה מותאמת למחירון שלך, ומה שחסר מסומן באדום.";
export const PLACEHOLDER = 'למשל: 12 מא"ז 1X16 ופחת 4X40';
