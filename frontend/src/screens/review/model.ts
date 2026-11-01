/**
 * The review screen's logic, kept out of React so it can be tested on its own (09 §6, prototype `vReview`).
 *
 * The screen computes no price, match or color (09 principle 7): every number arrives from the server as a decimal
 * string and is only formatted here, as a string, never through a JS number.
 */
import type { Finding, Quote, QuoteLine } from "../../api/client";

export type Status = QuoteLine["status"];
export type Filter = "all" | "review" | Status;
export type Tone = "acc" | "out" | "ok" | "warn" | "bad";

// --- money and numbers ---------------------------------------------------------------------------

function splitDecimal(amount: string): { negative: boolean; whole: string; frac: string } {
  const negative = amount.startsWith("-");
  const [whole = "0", frac = ""] = (negative ? amount.slice(1) : amount).split(".");
  return { negative, whole: whole.replace(/^0+(?=\d)/, "") || "0", frac };
}

const group = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** "4674.0000" → "₪4,674", "24.575" → "₪24.58" (half up, on the string), null → "—" (prototype `ils`). */
export function shekels(amount: string | null | undefined): string {
  if (amount == null) return "—";
  const { negative, whole, frac } = splitDecimal(amount);
  const padded = (frac + "000").slice(0, 3);
  let cents = BigInt(whole) * 100n + BigInt(padded.slice(0, 2));
  if (Number(padded[2]) >= 5) cents += 1n;
  const shekel = (cents / 100n).toString();
  const agorot = (cents % 100n).toString().padStart(2, "0");
  const sign = negative && cents !== 0n ? "-" : "";
  return `${sign}₪${group(shekel)}${agorot === "00" ? "" : `.${agorot}`}`;
}

/** A rate as whole percent: "0.2756" → "28%" (prototype `margin`). */
export function percent(rate: string | null | undefined): string {
  if (rate == null) return "—";
  const { negative, whole, frac } = splitDecimal(rate);
  const padded = (frac + "000").slice(0, 3);
  let pct = BigInt(whole) * 100n + BigInt(padded.slice(0, 2));
  if (Number(padded[2]) >= 5) pct += 1n;
  return `${negative && pct !== 0n ? "-" : ""}${pct}%`;
}

/** "17.000" → "17", "2.500" → "2.5". */
export function qtyText(qty: string): string {
  return qty.includes(".") ? qty.replace(/\.?0+$/, "") : qty;
}

/** The phone's sub line, where quantity and unit price go (09 §5.2): "4 × ₪185". */
export function qtyTimesPrice(line: QuoteLine): string {
  return `${qtyText(line.qty)} × ${shekels(line.unit_price)}`;
}

// --- filters, counts, progress (09 §6.2) ---------------------------------------------------------

export const FILTERS: { key: Filter; label: string; swatch?: "g" | "y" | "r" }[] = [
  { key: "all", label: "הכל" },
  { key: "review", label: "רק לבדיקה" },
  { key: "green", label: "ירוק", swatch: "g" },
  { key: "yellow", label: "צהוב", swatch: "y" },
  { key: "red", label: "אדום", swatch: "r" },
];

/** A second click on the active filter goes back to "הכל" (09 §6.2). */
export function nextFilter(current: Filter, clicked: Filter): Filter {
  return clicked === current ? "all" : clicked;
}

export function matches(line: QuoteLine, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "review") return line.status !== "green";
  return line.status === filter;
}

export function filterCounts(lines: QuoteLine[]): Record<Filter, number> {
  const count = (s: Status) => lines.filter((l) => l.status === s).length;
  const [green, yellow, red] = [count("green"), count("yellow"), count("red")];
  return { all: lines.length, review: yellow + red, green, yellow, red };
}

/** "9 מתוך 14 שורות מוכנות": ready means green (09 §6.2). */
export function progress(lines: QuoteLine[]): { ready: number; total: number; text: string; pct: number } {
  const ready = lines.filter((l) => l.status === "green").length;
  const total = lines.length;
  return {
    ready,
    total,
    text: `${ready} מתוך ${total} שורות מוכנות`,
    pct: total ? Math.round((100 * ready) / total) : 0,
  };
}

/** One tab per panel with its non-green count; none for a single panel (S09 decision 10). */
export function panelTabs(quote: Quote): { panelId: string | null; name: string; open: number }[] {
  if (quote.panels.length < 2) return [];
  return quote.panels.map((p) => ({
    panelId: p.panel_id,
    name: p.name,
    open: p.lines.filter((l) => l.status !== "green").length,
  }));
}

// --- rows of the lines table (09 §6.3) -----------------------------------------------------------

export const GROUP_LABELS: Record<string, string> = {
  feed: "הזנה",
  outputs: "יציאות",
  control: "פיקוד ובקרה",
  enclosure: "ארון",
};
export const SECTION_LABELS = { missing: "רכיבים שלא זוהו", extras: "פריטים נלווים ועבודה" } as const;

export type Row =
  | { kind: "group"; key: string; label: string }
  | { kind: "line"; key: string; line: QuoteLine; child: boolean }
  | { kind: "total"; key: string; label: string; amount: string }
  | { kind: "empty"; key: string };

/**
 * The table's rows for one panel. Lines arrive in display order from the server; this only drops what the filter
 * hides and puts a header wherever the group or section changes. The panel total row always shows.
 */
export function buildRows(panel: Quote["panels"][number], filter: Filter): Row[] {
  const rows: Row[] = [];
  let heading: string | null = null;
  const shown = panel.lines.filter((l) => matches(l, filter));
  for (const line of shown) {
    const label =
      line.section === "items" ? (GROUP_LABELS[line.line_group ?? ""] ?? "רכיבים") : SECTION_LABELS[line.section];
    if (label !== heading) {
      rows.push({ kind: "group", key: `g:${line.line_id}`, label });
      heading = label;
    }
    rows.push({ kind: "line", key: line.line_id, line, child: line.parent_line_id !== null });
  }
  if (shown.length === 0) rows.push({ kind: "empty", key: "empty" });
  rows.push({ kind: "total", key: "total", label: `סה״כ ${panel.name} לפני מע״מ`, amount: panel.totals.price_total });
  return rows;
}

/** ↑/↓ over the lines the filter shows (09 §8). Starts at the first line when nothing is selected. */
export function stepLine(ids: string[], current: string | null, dir: 1 | -1): string | null {
  if (ids.length === 0) return null;
  const at = current === null ? -1 : ids.indexOf(current);
  if (at === -1) return dir === 1 ? (ids[0] ?? null) : (ids[ids.length - 1] ?? null);
  return ids[Math.min(ids.length - 1, Math.max(0, at + dir))] ?? null;
}

// --- status shape and reason chips (09 §6.3, §9, §13) --------------------------------------------

export type Shape = "check" | "triangle" | "cross" | "box";

const STATUS_LABELS: Record<Status, string> = { green: "בטוח", yellow: "לבדיקה", red: "לא זוהה או שגוי" };

/** The shape that says what the color says, so color is never the only signal. Accessories get the box. */
export function statusMark(line: QuoteLine): { shape: Shape; label: string } {
  const label = STATUS_LABELS[line.status];
  if (line.line_type === "derived" || line.line_type === "labor")
    return { shape: "box", label: `פריט נלווה · ${label}` };
  return { shape: line.status === "green" ? "check" : line.status === "yellow" ? "triangle" : "cross", label };
}

const MATCH_CHIPS: Record<string, [string, Tone]> = {
  explicit_model: ["דגם מפורש", "acc"],
  memory: ["זיכרון התאמות", "acc"],
  kit: ["ערכה", "out"],
  model_not_written: ["דגם לא כתוב", "out"],
  context_page: ["עמוד נתונים", "out"],
  enclosure_includes: ["כולל פסי צבירה", "out"],
  inferred_attribute: ["הוסק מהמעגל", "warn"],
  ambiguous: ["כמה מוצרים מתאימים", "warn"],
  unmatched: ['אין מק"ט מתאים', "bad"],
  conflict: ["סתירה בין התכונות", "bad"],
};
const PRICE_CHIPS: Record<string, [string, Tone]> = {
  missing: ["אין מחיר", "bad"],
  stale: ["מחיר ישן", "warn"],
  discount_based: ["מחיר לפי הנחת מותג", "warn"],
};
const toneOf = (s: Status): Tone => (s === "red" ? "bad" : s === "yellow" ? "warn" : "ok");

type Reason = QuoteLine["status_reasons"][number];

function reasonChip(r: Reason, findings: Finding[]): [string, Tone] | null {
  const v = r.value as unknown;
  const code = typeof v === "string" ? v : v && typeof v === "object" ? (v as { code?: string }).code : undefined;
  const detail = v && typeof v === "object" ? (v as Record<string, string | undefined>) : {};
  switch (r.source) {
    case "match":
      if (code === "defaulted_attribute") return [`${detail.value ?? ""}: ברירת מחדל`.trim(), toneOf(r.status)];
      if (code === "brand_substituted")
        return [`בשרטוט: ${detail.drawing ?? "—"} · נבחר: ${detail.chosen ?? "—"}`, toneOf(r.status)];
      return code && MATCH_CHIPS[code] ? MATCH_CHIPS[code] : null;
    case "confidence":
      return r.status === "green" ? null : [`ביטחון קריאה ${String(v)}`, toneOf(r.status)];
    case "validator": {
      if (r.status === "green") return null; // an info finding shows in the findings box, not as a chip
      const f = findings.find((x) => x.finding_id === r.issue_id);
      return [f ? (f.title ?? f.message) : "ממצא של הבודק", toneOf(r.status)];
    }
    case "price":
      return code && PRICE_CHIPS[code] ? PRICE_CHIPS[code] : null;
    case "missing":
      return ["רכיב שלא זוהה", "bad"];
    case "user":
      return code === "manual" ? ["נוסף ידנית", "ok"] : ["אושר", "ok"];
    default:
      return null;
  }
}

/**
 * Every reason for the line's color as a chip (09 principle 3, §9). A yellow or red line always gets one: if no
 * reason has wording yet, a plain "לבדיקה" stands in, so a color is never left unexplained.
 */
export function reasonChips(line: QuoteLine, findings: Finding[]): { text: string; tone: Tone }[] {
  const chips = line.status_reasons
    .map((r) => reasonChip(r, findings))
    .filter((c): c is [string, Tone] => c !== null)
    .map(([text, tone]) => ({ text, tone }));
  const explained = chips.some((c) => c.tone === (line.status === "red" ? "bad" : "warn"));
  if (line.status !== "green" && !explained)
    chips.push({ text: STATUS_LABELS[line.status], tone: toneOf(line.status) });
  return chips;
}

// --- line detail (09 §6.4) ------------------------------------------------------------------------

const ATTRIBUTE_LABELS: Record<string, string> = {
  current: "זרם",
  poles: "קטבים",
  series: "דגם",
  load_current: "זרם עומס (INC)",
  type: "סוג",
  contacts: "מגעים",
  ac3_current: "זרם AC-3",
  coil_voltage: "מתח סליל",
  colors: "צבע",
  dimensions: "מידות",
  ip: "IP",
  ik: "IK",
  curve: "עקומה",
  breaking_capacity_ka: "כושר ניתוק",
  residual_ma: "זרם פחת",
};

export function attributeLabel(key: string): string {
  return ATTRIBUTE_LABELS[key] ?? key;
}

/** The source wordings of 09 §6.4, shortened to fit the third column as in the prototype. */
const SOURCE_LABELS: Record<string, [string, boolean]> = {
  drawing: ["שרטוט", false],
  cad_attrib: ["מאפיין בלוק CAD", false],
  graphic: ["סימון גרפי", false],
  shared_label: ["תווית משותפת לקבוצה", false],
  bom: ["כתב הכמויות", false],
  notes: ["מההערות הכלליות", false],
  circuit: ["הוסק מהמעגל", true],
  inferred: ["הוסק מהמעגל", true],
  tenant_default: ["לא כתוב בשרטוט. ברירת מחדל של המפעל", true],
  system_default: ["לא כתוב. ברירת מחדל תקנית", false],
  user: ["נקבע ידנית", false],
  series: ["נקבע לפי הדגם", false],
  gte: ["אין בקטלוג. נבחר ערך גבוה יותר", true],
  memory: ["זיכרון התאמות", false],
  missing: ["לא נמצא בשרטוט", true],
};
const LOW_READ = 0.85;

/** "שרטוט", 'שרטוט, ‏"3X6A"', "הוסק מ-F22–F25 (3X16A)", "עמוד 1". `warn` marks the ones 09 §6.4 highlights. */
export function sourceText(src: QuoteLine["sources"][number]): { text: string; warn: boolean } {
  const [label, warn] = SOURCE_LABELS[src.source] ?? [src.source, false];
  const lowRead = src.source === "drawing" && src.confidence != null && src.confidence < LOW_READ;
  let text = label;
  if (src.detail) {
    if (src.source === "circuit" || src.source === "inferred") text = `הוסק מ-${src.detail}`;
    else if (src.source === "notes") text = src.detail;
    else text = `${label}, ‏${src.detail}`;
  }
  if (lowRead) text = `נקרא ב-OCR (ביטחון ${src.confidence})`;
  return { text, warn: warn || lowRead };
}

/** "הצעה 10271", "הצעות 10288, 10271", "חוק רווח 25%", or "הוזן ידנית". */
export function priceSourceText(line: QuoteLine): string {
  const src = line.price_source;
  if (!src) return "הוזן ידנית";
  if (src.quotes.length) return `${src.quotes.length === 1 ? "הצעה" : "הצעות"} ${src.quotes.join(", ")}`;
  if (src.kind === "markup" || src.kind === "margin") return `חוק רווח ${percent(src.value)}`;
  return "הוזן ידנית";
}

export function lineFindings(line: QuoteLine, findings: Finding[]): Finding[] {
  return findings.filter((f) => f.line_ids.includes(line.line_id) || line.issue_ids.includes(f.finding_id));
}

/** "F1", …, "F17" → "F1–F17"; a run of 3 or more consecutive tags becomes a range. */
export function compactDesignators(tags: string[]): string[] {
  const out: string[] = [];
  let run: { prefix: string; from: number; to: number } | null = null;
  const flush = () => {
    if (!run) return;
    const { prefix, from, to } = run;
    if (to - from >= 2) out.push(`${prefix}${from}–${prefix}${to}`);
    else for (let n = from; n <= to; n++) out.push(`${prefix}${n}`);
    run = null;
  };
  for (const tag of tags) {
    const m = /^([A-Z]+)(\d+)$/.exec(tag);
    if (m && run && m[1] === run.prefix && Number(m[2]) === run.to + 1) {
      run.to += 1;
      continue;
    }
    flush();
    if (m) run = { prefix: m[1] ?? "", from: Number(m[2]), to: Number(m[2]) };
    else out.push(tag);
  }
  flush();
  return out;
}
