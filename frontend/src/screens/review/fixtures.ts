/**
 * Hand-written quotes for the review screen's tests (S09 decision 8): the states the NURSERY draft doesn't have,
 * such as a missing line, accessories and labor, a low-confidence read, a brand swap and two panels.
 */
import type { Finding, Quote, QuoteLine } from "../../api/client";

let n = 0;

export function line(over: Partial<QuoteLine> = {}): QuoteLine {
  n += 1;
  return {
    line_id: `ln_${String(n).padStart(26, "0")}`,
    line_type: "component",
    section: "items",
    line_group: "outputs",
    parent_line_id: null,
    included: false,
    sku: "S203M-C16",
    description: 'מא"ז ABB S203M 3P ‏16A',
    manufacturer: "ABB",
    qty: "1.000",
    unit: "unit",
    unit_price: "185.0000",
    unit_cost: "138.0000",
    line_total: "185.0000",
    line_cost: "138.0000",
    margin_pct: "0.2541",
    unit_margin: "47.0000",
    price_status: "ok",
    price_source: { kind: "fixed", source: "quote_import", quotes: ["10288"], value: null },
    cost_source: { type: "supplier_price_list", supplier: "ספק א׳ · מפיץ ABB", price_date: "2026-10-01" },
    status: "green",
    status_reasons: [{ source: "price", status: "green", value: "ok", issue_id: null }],
    issue_ids: [],
    designators: ["F1"],
    raw_text: ["F1", "3X16A"],
    sources: [{ attribute: "current", value: "16A", source: "drawing", detail: null, confidence: 0.95 }],
    note: null,
    explanation: null,
    alternatives: [],
    derived: null,
    approved: false,
    ...over,
  };
}

const zero = { green: 0, yellow: 0, red: 0 };

export function panel(name: string, lines: QuoteLine[], priceTotal = "0.0000"): Quote["panels"][number] {
  return {
    panel_id: `pnl_${name}`,
    name,
    lines,
    totals: { cost_total: "0", price_total: priceTotal, line_counts: zero, unpriced_count: 0, uncosted_count: 0 },
  };
}

export function quote(panels: Quote["panels"], findings: Finding[] = []): Quote {
  return {
    quote_id: "quo_01JD0000000000000000000001",
    name: "לוח בדיקה",
    drawing_id: null,
    drawing_number: "26/000",
    input_kind: "factory_drawing",
    version: 1,
    status: "draft",
    revision: 0,
    quote_date: "2026-10-13",
    currency: "ILS",
    coverage_pct: 100,
    panels,
    findings,
    totals: {
      cost_total: "0",
      price_total: "0",
      line_counts: zero,
      unpriced_count: 0,
      uncosted_count: 0,
      discount_pct: null,
      discount: null,
      net_total: "0",
      margin_abs: "0",
      margin_pct: null,
      vat_rate: "0.18",
      vat: "0",
      gross_total: "0",
    },
  };
}

export const red = (value: string) => ({ source: "price", status: "red" as const, value, issue_id: null });
