/**
 * The price-list screen's logic (prototype `vPrices`, `openEditor`, `saveEditor`, lines 1098–1208), kept out of React
 * so it can be tested on its own.
 *
 * Costs, prices and margins come from the server (07 §7.2.2, §7.3), worked out by the tenant's rules; the screen only
 * filters and formats them. Money and rates stay decimal strings: a typed amount is checked as text and sent as text,
 * and an average is taken in whole units with BigInt, never through a JS number (non-negotiable 5).
 */
import type { Schemas } from "../../api/client";
import { percent, shekels } from "../review/model";

export type Product = Schemas["ProductOut"];
export type SupplierRow = Schemas["SupplierPriceOut"];
export type History = Schemas["PriceHistoryOut"];
export type SanityWarning = Schemas["SanityWarningOut"];
/** What the editor sends: POST adds `source`, which PATCH does not take. */
export type ProductBody = Omit<Schemas["ProductIn"], "source" | "quote_id">;
export type SupplierBody = Schemas["SupplierPriceIn"];
export type Filter = "all" | "multi" | "nocost" | "low";

/** The table's query: the editor updates it in place after a save. */
export const PRODUCTS_KEY = ["price-list", "products"];

/** The prototype's chips, in its order (S19 decision 6). */
export const FILTERS: [Filter, string][] = [
  ["all", "הכול"],
  ["multi", "כמה ספקים"],
  ["nocost", "בלי עלות"],
  ["low", "רווח נמוך"],
];

/**
 * Families as the user reads them. The codes are the attribute schemas' (05 §4.4, BUG-039), which margin rules and
 * supplier preferences match on; the words are the prototype's where it has one (`CATALOG` `fam`).
 */
export const FAMILIES: [string, string][] = [
  ["circuit_breaker", 'מא"ז / מפסק'],
  ["rcd", "פחת"],
  ["rcbo", 'פחת משולב מא"ז'],
  ["switch_disconnector", "מנתק"],
  ["changeover_switch", "מחליף"],
  ["ats", "מחליף אוטומטי"],
  ["fuse", "נתיך"],
  ["contactor", "מגען"],
  ["overload_relay", "ממסר עומס יתר"],
  ["relay", "ממסר"],
  ["timer", "קוצב זמן"],
  ["voltage_relay", "ממסר מתח"],
  ["impulse_relay", "ממסר צעד"],
  ["time_switch", "שעון שבת"],
  ["shunt_trip", "סליל הפסקה"],
  ["temperature_controller", "בקר טמפרטורה"],
  ["surge_protector", "מגן ברק"],
  ["energy_meter", "מונה אנרגיה"],
  ["measuring_instrument", "מדידה"],
  ["current_transformer", "משנה זרם"],
  ["indicator_lamp", "נורה"],
  ["push_button", "לחצן"],
  ["selector_switch", "בורר"],
  ["aux_contact", "מגע עזר"],
  ["terminal", "מהדק"],
  ["socket_outlet", "שקע"],
  ["enclosure", "ארון"],
];
const FAMILY_LABELS = new Map(FAMILIES);

export function familyLabel(code: string): string {
  return FAMILY_LABELS.get(code) ?? code;
}

/** The prototype's units (`ed-unit`): "יח'", "מטר", "סט". */
export const UNITS: [string, string][] = [
  ["unit", "יח'"],
  ["meter", "מטר"],
  ["set", "סט"],
];

/** "כלול בארון" (S19 decision 2): the keys of the tenant's `enclosure_includes_default`. */
export const INCLUDES: [string, string][] = [
  ["busbar", "פסי צבירה"],
  ["n", "פס אפס"],
  ["pe", "פס הארקה"],
  ["panels", "פנלים"],
  ["doors", "דלתות"],
];

export const ENCLOSURE = "enclosure";

// --- numbers --------------------------------------------------------------------------------------------------------

const MONEY = /^\d{1,10}(\.\d{1,4})?$/; // numeric(14,4), below 10^10
const PERCENT = /^\d{1,2}(\.\d{1,2})?$/; // a discount below 100%

/** A typed amount as the API's decimal string: "1,920" or "abc" is not one; "19.20" stays as typed. */
export function moneyIn(text: string): string | null {
  const t = text.trim();
  return MONEY.test(t) ? t : null;
}

/** Hundredths of a percent, as an integer. */
function basisOf(rate: string): bigint {
  const [whole = "0", frac = ""] = rate.split(".");
  return BigInt(whole) * 10000n + BigInt((frac + "0000").slice(0, 4));
}

function trimRate(units: bigint): string {
  const s = units.toString().padStart(5, "0");
  return `${s.slice(0, -4)}.${s.slice(-4)}`.replace(/\.?0+$/, "");
}

/** "38" → "0.38", "32.5" → "0.325"; null for 0, 100 and anything that isn't a percentage. */
export function percentToRate(text: string): string | null {
  const t = text.trim();
  if (!PERCENT.test(t)) return null;
  const [whole = "0", frac = ""] = t.split(".");
  const units = BigInt(whole) * 100n + BigInt((frac + "00").slice(0, 2));
  return units === 0n ? null : trimRate(units);
}

/** "0.3800" → "38", "0.325" → "32.5" (the input shows a discount as percent). */
export function rateToPercent(rate: string): string {
  const units = basisOf(rate);
  const s = units.toString().padStart(3, "0");
  return `${s.slice(0, -2)}.${s.slice(-2)}`.replace(/\.?0+$/, "");
}

/** "0.25" → "25%" with a fraction kept: "0.125" → "12.5%". For rules, where 12.5% is what the user typed. */
export function ratePercent(rate: string | null | undefined): string {
  return rate == null ? "—" : `${rateToPercent(rate)}%`;
}

// --- the table ------------------------------------------------------------------------------------------------------

/** The prototype's search: the name, the sku, the brand, and every supplier's name and sku, ignoring case. */
export function matches(p: Product, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  const hay = [
    p.display_name,
    p.manufacturer_sku,
    p.brand,
    ...p.suppliers.flatMap((s) => [s.supplier_name, s.supplier_sku]),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return hay.includes(needle);
}

/** S18's filters, on the loaded list: "בלי עלות" is no supplier and not a consumable; "רווח נמוך" is below the floor. */
export function inFilter(p: Product, f: Filter): boolean {
  switch (f) {
    case "nocost":
      return p.suppliers.length === 0 && !p.consumable;
    case "multi":
      return p.suppliers.length > 1;
    case "low":
      return p.below_margin_floor;
    default:
      return true;
  }
}

export function visible(products: Product[], q: string, f: Filter): Product[] {
  return products.filter((p) => matches(p, q) && inFilter(p, f));
}

export interface Stats {
  count: number;
  multi: number;
  noCost: number;
  /** "28%", or "—" with no margin anywhere */
  avgMargin: string;
}

/** The four cards over the whole list, not the filtered rows (prototype `vPrices`). */
export function stats(products: Product[]): Stats {
  const margins = products.map((p) => p.margin_pct).filter((m): m is string => m != null);
  let avgMargin = "—";
  if (margins.length) {
    const sum = margins.reduce((acc, m) => acc + (m.startsWith("-") ? -basisOf(m.slice(1)) : basisOf(m)), 0n);
    const n = BigInt(margins.length);
    // whole percent, half away from zero: sum is in 1/10000, so percent is sum / (100 n)
    const twice = (sum * 2n) / (100n * n);
    const pct = twice >= 0n ? (twice + 1n) / 2n : -((-twice + 1n) / 2n);
    avgMargin = `${pct}%`;
  }
  return {
    count: products.length,
    multi: products.filter((p) => p.suppliers.length > 1).length,
    noCost: products.filter((p) => inFilter(p, "nocost")).length,
    avgMargin,
  };
}

/** The supplier the cost came from (07 §7.2.2's order), else the first: preferred, then cheapest. */
export function costSupplier(p: Product): SupplierRow | null {
  const id = (p.cost_source as { supplier_price_id?: string } | null)?.supplier_price_id;
  return p.suppliers.find((s) => s.id === id) ?? p.suppliers[0] ?? null;
}

/** The prototype shows a supplier's name up to its " · ": "ספק א׳ · מפיץ ABB" → "ספק א׳". */
export function supplierShort(s: SupplierRow): string {
  return s.supplier_name ? (s.supplier_name.split(" · ")[0] ?? s.supplier_name) : "עלות ידנית";
}

/** Under the sale price: "מחיר קבוע", or the rule that priced it ("חוק רווח 25%"). */
export function saleModeText(p: Product): string {
  if (p.sale_mode === "fixed") return "מחיר קבוע";
  const rule = p.margin_rule as { kind?: string; value?: string | null } | null;
  if (!rule?.value) return "חוק רווח";
  return `${rule.kind === "margin" ? "רווח" : "חוק רווח"} ${ratePercent(rule.value)}`;
}

const SOURCES: Record<string, string> = {
  supplier_price_list: "מחירון ספק",
  manual_entry: "הוזן ידנית",
  quote_import: "מהצעה קודמת",
  brand_discount: "הנחת מותג",
};

/** The source column: where the product came from, and the quote it was typed in ("הוזן בהצעה NURSERY"). */
export function sourceText(p: Product): string {
  if (p.consumable && p.suppliers.length === 0) return "חומר עזר";
  if (p.source === "manual_entry" && p.entered_in_quote_name) return `הוזן ב${p.entered_in_quote_name}`;
  return SOURCES[p.source] ?? p.source;
}

/** "28.10" (prototype `hist[0].d`), in the tenant's timezone. */
export function dayMonth(iso: string, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone, day: "numeric", month: "numeric" }).formatToParts(
    new Date(iso),
  );
  const get = (type: string) => parts.find((x) => x.type === type)?.value ?? "";
  return `${get("day")}.${get("month")}`;
}

/** "1.6.2026", as 10 §8's message writes the previous price's date. */
export function fullDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-");
  return `${Number(d)}.${Number(m)}.${y}`;
}

// --- 10 §8's warnings -----------------------------------------------------------------------------------------------

/** The warning beside a typed cost (10 §8's table). Every one only warns: Save stays available (S19 decision 4). */
export function warningText(w: SanityWarning): string {
  switch (w.code) {
    case "far_from_list":
      return `המחיר רחוק ממחירון היצרן (${shekels(w.reference)}). לבדוק?`;
    case "far_from_similar":
      return `המחיר רחוק ממוצרים דומים במחירון שלך (${shekels(w.reference)}). לבדוק?`;
    default:
      return `המחיר הקודם היה ${shekels(w.reference)}${w.reference_date ? ` מ-${fullDate(w.reference_date)}` : ""}. לעדכן?`;
  }
}

// --- the editor -----------------------------------------------------------------------------------------------------

export interface DraftRow {
  key: string;
  /** a saved row's id; a new row has none */
  id?: string;
  supplierId: string | null;
  name: string;
  supplierSku: string;
  cost: string;
  lead: string;
  preferred: boolean;
  /** as saved, to tell whether the cost was typed here */
  saved?: SupplierRow;
}

export interface Draft {
  name: string;
  sku: string;
  brand: string;
  family: string;
  unit: string;
  mode: "fixed" | "rule";
  sale: string;
  rows: DraftRow[];
  consumable: boolean;
  includes: Record<string, boolean> | null;
}

let keys = 0;
const nextKey = () => `r${++keys}`;

export function blankRow(): DraftRow {
  return { key: nextKey(), supplierId: null, name: "", supplierSku: "", cost: "", lead: "", preferred: false };
}

function rowOf(s: SupplierRow): DraftRow {
  return {
    key: nextKey(),
    id: s.id,
    supplierId: s.supplier_id,
    name: s.supplier_name ?? "",
    supplierSku: s.supplier_sku ?? "",
    cost: plainAmount(s.unit_cost),
    lead: s.lead_days == null ? "" : String(s.lead_days),
    preferred: s.preferred,
    saved: s,
  };
}

/** "130.0000" → "130", "31.5000" → "31.5": the stored scale is not what the user typed. */
export function plainAmount(amount: string): string {
  return amount.includes(".") ? amount.replace(/\.?0+$/, "") : amount;
}

/** A new product is a fixed price by default (prototype `openEditor`); a new cabinet starts from the tenant's
 * defaults for what it includes. */
export function draftOf(p: Product | null, includesDefault: Record<string, boolean>): Draft {
  if (!p)
    return {
      name: "",
      sku: "",
      brand: "",
      family: "",
      unit: "unit",
      mode: "fixed",
      sale: "",
      rows: [],
      consumable: false,
      includes: null,
    };
  return {
    name: p.display_name,
    sku: p.manufacturer_sku ?? "",
    brand: p.brand ?? "",
    family: p.family,
    unit: p.unit,
    mode: p.sale_mode,
    sale: p.fixed_price ? plainAmount(p.fixed_price) : "",
    rows: p.suppliers.map(rowOf),
    consumable: p.consumable,
    includes: p.includes ? includesOf(p.includes) : p.family === ENCLOSURE ? { ...includesDefault } : null,
  };
}

function includesOf(raw: Record<string, unknown>): Record<string, boolean> {
  return Object.fromEntries(INCLUDES.map(([k]) => [k, raw[k] === true]));
}

/** A row nobody typed in: dropped, like the prototype's empty rows. */
const isBlank = (r: DraftRow) => !r.name.trim() && !r.supplierSku.trim() && !r.cost.trim() && !r.lead.trim();

/** Whether the row's cost was typed in this editor: a new row, or a saved one whose cost changed. */
export function typedHere(r: DraftRow): boolean {
  if (!r.saved) return true;
  const typed = moneyIn(r.cost);
  return typed === null || basisOf(typed) !== basisOf(r.saved.unit_cost);
}

export type DraftError = { field: "name" | "family" | "sale" | "rows"; row?: string; message: string };

export interface Saved {
  body: ProductBody;
  /** the hint the prototype gives a rule with no cost, now allowed (S19 decision 1) */
  noCost: boolean;
}

/**
 * The editor's checks (prototype `saveEditor`) and the body for POST, or for PATCH (every field sent; the server
 * logs only what changed). Differences from the prototype: a family is required (07 §7.2.1), a rule with no supplier
 * saves (S19 decision 1), a row with a name but no valid cost is an error rather than dropped, and a consumable with
 * no sale price is saved on the rule, since `fixed` needs its price (07 §7.2.1).
 */
export function toBody(d: Draft, today: string): Saved | DraftError {
  if (!d.name.trim()) return { field: "name", message: "חסר שם מוצר" };
  if (!d.family) return { field: "family", message: "בחרו משפחה" };
  const rows = d.rows.filter((r) => !isBlank(r));
  for (const r of rows) {
    if (moneyIn(r.cost) === null) return { field: "rows", row: r.key, message: "עלות חסרה או לא תקינה" };
    if (r.lead.trim() && !/^\d{1,4}$/.test(r.lead.trim()))
      return { field: "rows", row: r.key, message: "ימי אספקה: מספר שלם" };
  }
  if (rows.filter((r) => !r.name.trim()).length > 1)
    return { field: "rows", message: "רק עלות אחת יכולה להיות בלי ספק" };
  const names = rows.map((r) => r.name.trim()).filter(Boolean);
  if (new Set(names).size !== names.length) return { field: "rows", message: "אותו ספק מופיע פעמיים" };

  const sale = d.sale.trim() ? moneyIn(d.sale) : null;
  if (d.sale.trim() && sale === null) return { field: "sale", message: "מחיר המכירה לא תקין" };
  const priced = sale !== null && basisOf(sale) > 0n;
  if (d.mode === "fixed" && !priced && !d.consumable)
    return { field: "sale", message: "הזינו מחיר מכירה, או בחרו חוק רווח" };
  const mode = d.mode === "fixed" && !priced ? "rule" : d.mode;

  const suppliers: SupplierBody[] = rows.map((r) => {
    const cost = moneyIn(r.cost) as string;
    const typed = typedHere(r);
    const named = r.name.trim();
    const sameSupplier = r.saved && (r.saved.supplier_name ?? "") === named;
    return {
      id: r.id ?? null,
      supplier_id: sameSupplier ? r.supplierId : null,
      supplier_name: sameSupplier || !named ? null : named,
      supplier_sku: r.supplierSku.trim() || null,
      unit_cost: cost,
      currency: r.saved?.currency ?? "ILS",
      lead_days: r.lead.trim() ? Number(r.lead.trim()) : null,
      price_date: typed || !r.saved ? today : r.saved.price_date,
      valid_until: typed ? null : (r.saved?.valid_until ?? null),
      preferred: r.preferred,
      // a cost typed here is a manual entry, which 10 §8 checks on save; an untouched row keeps where it came from
      source: typed ? "manual_entry" : (r.saved?.source as SupplierBody["source"]),
    };
  });
  return {
    body: {
      display_name: d.name.trim(),
      manufacturer_sku: d.sku.trim() || null,
      brand: d.brand.trim() || null,
      family: d.family,
      unit: d.unit,
      sale_mode: mode,
      fixed_price: priced ? sale : null,
      includes: d.family === ENCLOSURE ? d.includes : null,
      consumable: d.consumable,
      suppliers,
    },
    noCost: mode === "rule" && suppliers.length === 0,
  };
}

export const isError = (x: Saved | DraftError): x is DraftError => "field" in x;

// --- history --------------------------------------------------------------------------------------------------------

const FIELD_LABELS: Record<string, string> = {
  display_name: "שם המוצר",
  manufacturer_sku: 'מק"ט יצרן',
  brand: "יצרן",
  family: "משפחה",
  unit: "יחידה",
  includes: "כלול בארון",
  catalog_item_id: "קישור לקטלוג",
};

type Snapshot = Record<string, unknown> | null;
const value = (x: Snapshot) => (x && "value" in x ? x.value : undefined);

/**
 * One history row as the prototype writes it (`hist[].t`): "נוצר ידנית", "מחיר מכירה ₪185 ← ₪195", a supplier added
 * or removed. `names` gives a supplier's name for a row that is gone from the product.
 */
export function historyText(h: History, names: Map<string, string>): string {
  const supplierName = (x: Snapshot) => {
    const id = x?.supplier_id as string | null | undefined;
    return id ? (names.get(id) ?? "ספק") : "עלות ידנית";
  };
  switch (h.field) {
    case "created":
      return (h.new as { source?: string } | null)?.source === "manual_entry" ? "נוצר ידנית" : "נוסף למחירון";
    case "fixed_price":
      return `מחיר מכירה ${shekels(value(h.old) as string | null)} ← ${shekels(value(h.new) as string | null)}`;
    case "sale_mode":
      return value(h.new) === "fixed" ? "עבר למחיר קבוע" : "עבר לחוק הרווח";
    case "consumable":
      return value(h.new) === true ? "סומן כחומר עזר" : "בוטל סימון חומר עזר";
    case "supplier": {
      if (!h.old) return `נוסף ספק: ${supplierName(h.new)}, ${shekels(h.new?.unit_cost as string)}`;
      if (!h.new) return `הוסר ספק: ${supplierName(h.old)}`;
      if (h.old.unit_cost !== h.new.unit_cost) {
        const who = h.new.supplier_id ? `עלות ${supplierName(h.new)}` : "עלות ידנית";
        return `${who} ${shekels(h.old.unit_cost as string)} ← ${shekels(h.new.unit_cost as string)}`;
      }
      if (h.old.preferred !== h.new.preferred && h.new.preferred) return `ספק מועדף: ${supplierName(h.new)}`;
      return `עודכנו פרטי ספק: ${supplierName(h.new)}`;
    }
    default:
      return `עודכן: ${FIELD_LABELS[h.field] ?? h.field}`;
  }
}

/** The editor's note on open drafts (prototype `openEditor`): "NURSERY (F1, F2 · Q0)". */
export function draftsText(p: Product): string | null {
  if (!p.used_in_drafts.length) return null;
  const each = p.used_in_drafts.map((u) => `${u.quote_name} (${u.lines.join(" · ")})`).join(", ");
  return p.used_in_drafts.length === 1 ? `בשימוש בטיוטה הפתוחה ${each}` : `בשימוש בטיוטות הפתוחות ${each}`;
}

/** The toast after saving (prototype `saveEditor`, line 1205): sent quotes never change, and the open drafts' lines
 * now tagged "מחיר חדש במחירון" (07 §7.2.3, S23). */
export function savedText(before: Product | null, after: Product): string {
  if (!before) return "המוצר נוסף למחירון";
  const changed = (before.unit_price ?? "") !== (after.unit_price ?? "");
  if (!changed) return "נשמר";
  const used = after.used_in_drafts.reduce((n, u) => n + u.fresh, 0);
  const tagged = used === 1 ? "שורה אחת מסומנת" : `${used} שורות מסומנות`;
  return `נשמר. הצעות שנשלחו לא השתנו${used ? `; בטיוטה הפתוחה ${tagged} "מחיר חדש"` : ""}`;
}

export { percent, shekels };
