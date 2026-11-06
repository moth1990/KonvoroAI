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
  outside: "מחוץ ללוח", // 07 §7.4: priced apart, not in the enclosure's modules (S22)
};
export const SECTION_LABELS = { missing: "רכיבים שלא זוהו", extras: "פריטים נלווים ועבודה" } as const;

export type Row =
  | { kind: "group"; key: string; label: string }
  | { kind: "line"; key: string; line: QuoteLine; child: boolean }
  | { kind: "removed"; key: string; lineIds: string[] }
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
  // 09 §6.3 item 4: "X פריטים נלווים הוסרו" with "החזר", at the end of the accessories
  if (panel.removed.length) {
    if (heading !== SECTION_LABELS.extras) rows.push({ kind: "group", key: "g:removed", label: SECTION_LABELS.extras });
    rows.push({ kind: "removed", key: "removed", lineIds: panel.removed.map((r) => r.line_id) });
  }
  rows.push({ kind: "total", key: "total", label: `סה״כ ${panel.name} לפני מע״מ`, amount: panel.totals.price_total });
  return rows;
}

/**
 * 09 §7.2: after an approval, the next line that still needs checking (not green), in table order, going on from the
 * start at the end. `ids` are the table's lines in order; null when none is left.
 */
export function nextToCheck(ids: string[], lines: QuoteLine[], current: string | null): string | null {
  const byId = new Map(lines.map((l) => [l.line_id, l]));
  const at = current === null ? -1 : ids.indexOf(current);
  for (let step = 1; step <= ids.length; step++) {
    const id = ids[(at + step + ids.length) % ids.length];
    if (id === undefined || id === current) continue;
    if (byId.get(id)?.status !== "green") return id;
  }
  return null;
}

/** A line whose price is typed in its row (prototype line 879): no price, not a kit part priced in its parent. */
export function takesPrice(line: QuoteLine): boolean {
  // S27b: a line waiting for a decision takes a product first, not a price (07 §7.1)
  return (
    line.unit_price == null &&
    !line.included &&
    !line.pending &&
    (line.line_type === "component" || line.line_type === "manual")
  );
}

/** 09 §7.13: Enter in a price cell saves it and moves to the next line with no price, after this one. */
export function nextUnpriced(ids: string[], lines: QuoteLine[], current: string): string | null {
  const byId = new Map(lines.map((l) => [l.line_id, l]));
  const at = ids.indexOf(current);
  for (let step = 1; step < ids.length; step++) {
    const id = ids[(at + step) % ids.length];
    const line = id === undefined ? undefined : byId.get(id);
    if (line && id !== current && takesPrice(line)) return id ?? null;
  }
  return null;
}

/** The send dialog's warnings (09 §7.12, prototype `send`): red and yellow lines, and lines left out of the sum. */
export function sendSummary(quote: Quote): { red: number; yellow: number; unpriced: number; pending: number } {
  const lines = quote.panels.flatMap((p) => p.lines);
  return {
    red: lines.filter((l) => l.status === "red").length,
    yellow: lines.filter((l) => l.status === "yellow").length,
    unpriced: quote.totals.unpriced_count,
    pending: pendingCount(quote),
  };
}

/** S27b (09 §6.1): the lines waiting for a decision, a product not in the catalog. */
export function pendingCount(quote: Quote): number {
  return quote.panels.flatMap((p) => p.lines).filter((l) => l.pending).length;
}

export function pendingText(n: number): string {
  return n === 1 ? "מוצר חדש אחד בשרטוט" : `${n} מוצרים חדשים בשרטוט`;
}

/** 09 §7.16: the form's attribute names, as the line detail names them. */
export function newProductLabel(name: string): string {
  return NEW_PRODUCT_LABELS[name] ?? attributeLabel(name);
}

const NEW_PRODUCT_LABELS: Record<string, string> = {
  poles: "קטבים",
  curve: "עקומה",
  neutral: "אפס (N)",
  residual_ma: "זרם פחת (mA)",
  rcd_type: "סוג פחת",
  coil_voltage_v: "מתח סליל (V)",
  trip_unit: "יחידת הגנה",
  range_min_a: "טווח מ- (A)",
  range_max_a: "טווח עד (A)",
  setting_a: "כיול (A)",
  utilization: "קטגוריית עבודה",
  astronomical: "שעון אסטרונומי",
};

/** A rate under a floor, both decimal strings from the server ("0.1200" < "0.1500"). */
export function belowFloor(rate: string | null | undefined, floor: string | null | undefined): boolean {
  return rate != null && floor != null && Number(rate) < Number(floor);
}

/** A typed amount as the API takes it: digits and one decimal point, more than zero; null when it is not one. */
export function parseAmount(text: string): string | null {
  const clean = text.replace(/[^\d.]/g, "");
  if (!/^\d+(\.\d{1,4})?$/.test(clean) || !/[1-9]/.test(clean)) return null;
  return clean;
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
  not_in_catalog: ["אין בקטלוג מוצר עם הערכים האלה", "bad"], // 09 §7.4, after a value set by hand
  resolved: ["נבחר ידנית", "ok"], // 09 §7.8: a missing line the estimator picked a product for
};
const PENDING_CHIP: [string, Tone] = ["מוצר חדש בשרטוט", "bad"]; // S27b (09 §6.3)
const PRICE_CHIPS: Record<string, [string, Tone]> = {
  missing: ["אין מחיר", "bad"],
  stale: ["מחיר ישן", "warn"],
  discount_based: ["מחיר לפי הנחת מותג", "warn"],
};
const toneOf = (s: Status): Tone => (s === "red" ? "bad" : s === "yellow" ? "warn" : "ok");

type Reason = QuoteLine["status_reasons"][number];

function reasonChip(r: Reason, findings: Finding[]): [string, Tone] | null {
  const chip = reasonChipOf(r, findings);
  // an approved line (09 §7.2): what made it yellow or red is still said, but no longer as a warning
  return chip && r.was && r.was !== "green" ? [chip[0], "ok"] : chip;
}

function reasonChipOf(r: Reason, findings: Finding[]): [string, Tone] | null {
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
      if (r.status === "green") return null; // an info finding shows in the findings box; an approved one is gone
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
 * 09 §6.3's price chips (prototype `lineRow`): "מחיר להצעה הזו", "מחיר חדש במחירון: X" and "רווח נמוך X%". A sent
 * version shows none of the first two: it never changes.
 */
export function priceChips(line: QuoteLine, locked: boolean): { text: string; tone: Tone }[] {
  const chips: { text: string; tone: Tone }[] = [];
  if (line.override) chips.push({ text: "מחיר להצעה הזו", tone: "acc" });
  if (!locked && line.fresh_price != null)
    chips.push({ text: `מחיר חדש במחירון: ${shekels(line.fresh_price)}`, tone: "warn" });
  if (line.below_floor) chips.push({ text: `רווח נמוך ${percent(line.margin_pct)}`, tone: "warn" });
  return chips;
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
  if (line.pending && line.line_type !== "missing") {
    // S27b: a product not in the catalog says so, in place of "אין מק"ט מתאים"
    const at = chips.findIndex((c) => c.text === MATCH_CHIPS.unmatched?.[0]);
    const chip = { text: PENDING_CHIP[0], tone: PENDING_CHIP[1] };
    if (at >= 0) chips[at] = chip;
    else chips.unshift(chip);
  }
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
  current_a: "זרם",
};

export function attributeLabel(key: string): string {
  return ATTRIBUTE_LABELS[key] ?? key;
}

// --- the product picker (09 §6.4, §6.6, §7.4, §7.13; S23b) --------------------------------------------------------

const UNITS: Record<string, string> = { current_a: "A", breaking_capacity_ka: "kA" };

/** An attribute's value with its unit when the value is a bare number ("16" → "16A"); the fixture's "20A" stays. */
export function attributeValue(attribute: string, value: string | null): string | null {
  if (value == null) return null;
  const unit = UNITS[attribute];
  return unit && /^\d+(\.\d+)?$/.test(value) ? `${value}${unit}` : value;
}

/** The value the dropdown shows as chosen: the line's own, as a bare number, when the list has it. */
export function attributeChoice(value: string | null, options: string[]): string {
  if (value == null) return "";
  const n = /^(\d+(?:\.\d+)?)/.exec(value)?.[1];
  return n && options.some((o) => Number(o) === Number(n)) ? (options.find((o) => Number(o) === Number(n)) ?? "") : "";
}

/** "30" or "30%" typed as a discount → "0.3", the API's fraction; null for anything but 0 < x < 100. */
export function discountFraction(text: string): string | null {
  const clean = text.trim().replace(/%$/, "").trim();
  if (!/^\d{1,2}(\.\d{1,2})?$/.test(clean)) return null;
  const pct = Number(clean);
  if (!(pct > 0 && pct < 100)) return null;
  return String(Number((pct / 100).toFixed(4)));
}

/** 09 §6.4's explanation on a missing line, with what was read beside the symbol when there is anything. */
export function missingText(line: QuoteLine): string {
  const read = line.explanation?.trim();
  const head = read ? `בשרטוט כתוב ״${read}״ ליד סימן שהזיהוי לא סימן.` : "בשרטוט יש כאן סימן שהזיהוי לא סימן.";
  return `${head} אם יש כאן רכיב, בחרו מוצר. אם לא, מחקו את השורה.`;
}

/** A product in the picker's list: "ABB · S203M-C16" and its price, or "אין מחיר". */
export function choiceMeta(c: { sku: string | null; manufacturer: string | null }): string {
  return [c.manufacturer, c.sku].filter(Boolean).join(" · ");
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
