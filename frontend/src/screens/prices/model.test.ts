import { describe, expect, it } from "vitest";

import {
  blankRow,
  costSupplier,
  draftOf,
  draftsText,
  familyLabel,
  historyText,
  isError,
  matches,
  moneyIn,
  percentToRate,
  rateToPercent,
  saleModeText,
  savedText,
  sourceText,
  stats,
  supplierShort,
  toBody,
  visible,
  warningText,
  type Draft,
  type History,
  type Product,
  type SupplierRow,
} from "./model";

const TODAY = "2026-11-03";

function row(over: Partial<SupplierRow> = {}): SupplierRow {
  return {
    id: `psp_${Math.random()}`,
    supplier_id: "sup_a",
    supplier_name: "ספק א׳ · מפיץ ABB",
    supplier_sku: null,
    unit_cost: "138.0000",
    currency: "ILS",
    lead_days: 2,
    price_date: "2026-10-01",
    valid_until: null,
    preferred: true,
    source: "supplier_price_list",
    in_force: true,
    ...over,
  };
}

function product(over: Partial<Product> = {}): Product {
  return {
    id: `prd_${Math.random()}`,
    display_name: 'מא"ז ABB S203M 3P ‏16A',
    manufacturer_sku: "S203M-C16",
    brand: "ABB",
    family: "circuit_breaker",
    unit: "unit",
    sale_mode: "fixed",
    fixed_price: "185.0000",
    includes: null,
    consumable: false,
    source: "quote_import",
    catalog_item_id: null,
    list_price: null,
    list_currency: null,
    entered_in_quote: null,
    entered_in_quote_name: null,
    entered_by: null,
    entered_at: null,
    last_changed_at: null,
    sanity: null,
    suppliers: [row()],
    unit_cost: "138.0000",
    price_status: "ok",
    cost_source: null,
    unit_price: "185.0000",
    margin_rule: { level: "sku", kind: "fixed", value: null, fixed_price: "185.0000" },
    margin_pct: "0.2541",
    below_margin_floor: false,
    history: [],
    used_in_drafts: [],
    ...over,
  };
}

function draft(over: Partial<Draft> = {}): Draft {
  return { ...draftOf(null, {}), name: "ממסר", family: "relay", sale: "130", ...over };
}

describe("search and filters", () => {
  const two = product({
    display_name: "מפסק פחת",
    manufacturer_sku: "F204A-40/0.03",
    suppliers: [
      row(),
      row({ supplier_id: "sup_b", supplier_name: "ספק ב׳", supplier_sku: "B-20316", preferred: false }),
    ],
  });
  const none = product({ display_name: "ממסר חוסר מתח", manufacturer_sku: null, brand: null, suppliers: [] });
  const consumable = product({ display_name: "מהדק בדיקה", suppliers: [], consumable: true });
  const low = product({ display_name: "נורה", below_margin_floor: true });
  const all = [two, none, consumable, low];

  it("searches the name, the sku, the brand and every supplier's name and sku, ignoring case", () => {
    expect(matches(two, "f204a")).toBe(true);
    expect(matches(two, "ספק ב")).toBe(true);
    expect(matches(two, "b-20316")).toBe(true);
    expect(matches(two, "abb")).toBe(true);
    expect(matches(none, "ABB")).toBe(false);
    expect(matches(none, "  ")).toBe(true);
  });

  it("filters as S18's API does: no cost leaves out consumables", () => {
    expect(visible(all, "", "multi")).toEqual([two]);
    expect(visible(all, "", "nocost")).toEqual([none]);
    expect(visible(all, "", "low")).toEqual([low]);
    expect(visible(all, "", "all")).toHaveLength(4);
    expect(visible(all, "חוסר", "multi")).toEqual([]);
  });

  it("counts over the whole list, and averages margins in whole percent without a float", () => {
    const s = stats([
      product({ margin_pct: "0.2756" }),
      product({ margin_pct: "0.2500" }),
      product({ margin_pct: null, suppliers: [] }),
    ]);
    expect(s).toEqual({ count: 3, multi: 0, noCost: 1, avgMargin: "26%" });
    expect(stats([product({ margin_pct: "0.2750" })]).avgMargin).toBe("28%"); // 27.5 rounds up
    expect(stats([product({ margin_pct: "-0.1000" })]).avgMargin).toBe("-10%");
    expect(stats([]).avgMargin).toBe("—");
  });
});

describe("the table's cells", () => {
  it("shows the supplier the cost came from, up to its ' · '", () => {
    const b = row({ id: "psp_b", supplier_name: "ספק ב׳ · מפיץ ABB", preferred: false, unit_cost: "131.0000" });
    const p = product({ suppliers: [row(), b], cost_source: { supplier_price_id: "psp_b" } });
    expect(costSupplier(p)).toBe(b);
    expect(supplierShort(b)).toBe("ספק ב׳");
    expect(supplierShort(row({ supplier_name: null, supplier_id: null }))).toBe("עלות ידנית");
    expect(costSupplier(product({ suppliers: [] }))).toBeNull();
  });

  it("names the sale mode and the rule that priced it", () => {
    expect(saleModeText(product())).toBe("מחיר קבוע");
    const rule = { level: "default", kind: "markup", value: "0.25", fixed_price: null };
    expect(saleModeText(product({ sale_mode: "rule", margin_rule: rule }))).toBe("חוק רווח 25%");
    expect(saleModeText(product({ sale_mode: "rule", margin_rule: { ...rule, kind: "margin", value: "0.125" } }))).toBe(
      "רווח 12.5%",
    );
  });

  it("names the source, with the quote a product was typed in", () => {
    expect(sourceText(product())).toBe("מהצעה קודמת");
    expect(sourceText(product({ source: "manual_entry", entered_in_quote_name: "NURSERY" }))).toBe("הוזן בNURSERY");
    expect(sourceText(product({ consumable: true, suppliers: [] }))).toBe("חומר עזר");
  });

  it("labels families in Hebrew and keeps an unknown code", () => {
    expect(familyLabel("rcd")).toBe("פחת");
    expect(familyLabel("enclosure")).toBe("ארון");
    expect(familyLabel("something_new")).toBe("something_new");
  });
});

describe("numbers as strings", () => {
  it("accepts an amount as typed, and nothing that isn't one", () => {
    expect(moneyIn(" 19.20 ")).toBe("19.20");
    expect(moneyIn("1,920")).toBeNull();
    expect(moneyIn("1e3")).toBeNull();
    expect(moneyIn("1.23456")).toBeNull();
    expect(moneyIn("-5")).toBeNull();
  });

  it("turns a discount in percent into a rate and back", () => {
    expect(percentToRate("38")).toBe("0.38");
    expect(percentToRate("32.5")).toBe("0.325");
    expect(percentToRate("5")).toBe("0.05");
    expect(percentToRate("0")).toBeNull();
    expect(percentToRate("100")).toBeNull();
    expect(percentToRate("x")).toBeNull();
    expect(rateToPercent("0.3800")).toBe("38");
    expect(rateToPercent("0.325")).toBe("32.5");
    expect(rateToPercent("0.05")).toBe("5");
  });
});

describe("10 §8's warnings", () => {
  it("writes the spec's messages", () => {
    expect(warningText({ code: "far_from_list", reference: "210.0000", reference_date: null })).toBe(
      "המחיר רחוק ממחירון היצרן (₪210). לבדוק?",
    );
    expect(warningText({ code: "jump_from_previous", reference: "138.0000", reference_date: "2026-06-01" })).toBe(
      "המחיר הקודם היה ₪138 מ-1.6.2026. לעדכן?",
    );
    expect(warningText({ code: "far_from_similar", reference: "31.5", reference_date: null })).toContain("₪31.50");
  });
});

describe("the editor", () => {
  it("opens a product with its amounts as typed, and a new cabinet with the tenant's includes", () => {
    const d = draftOf(product(), {});
    expect([d.sale, d.rows[0]?.cost, d.rows[0]?.lead, d.mode]).toEqual(["185", "138", "2", "fixed"]);
    const cabinet = draftOf(product({ family: "enclosure", includes: null }), { busbar: true, doors: false });
    expect(cabinet.includes).toEqual({ busbar: true, doors: false });
    expect(draftOf(product({ family: "enclosure", includes: { busbar: false } }), { busbar: true }).includes).toEqual({
      busbar: false,
      n: false,
      pe: false,
      panels: false,
      doors: false,
    });
  });

  it("needs a name, a family, and a sale price unless it is on the rule or a consumable", () => {
    expect(toBody(draft({ name: " " }), TODAY)).toMatchObject({ field: "name", message: "חסר שם מוצר" });
    expect(toBody(draft({ family: "" }), TODAY)).toMatchObject({ field: "family" });
    expect(toBody(draft({ sale: "" }), TODAY)).toMatchObject({
      field: "sale",
      message: "הזינו מחיר מכירה, או בחרו חוק רווח",
    });
    expect(toBody(draft({ sale: "abc" }), TODAY)).toMatchObject({ field: "sale" });
  });

  it("saves a rule with no supplier, with the hint (S19 decision 1)", () => {
    const out = toBody(draft({ mode: "rule", sale: "" }), TODAY);
    expect(isError(out)).toBe(false);
    if (isError(out)) return;
    expect(out.noCost).toBe(true);
    expect(out.body).toMatchObject({ sale_mode: "rule", fixed_price: null, suppliers: [] });
  });

  it("saves a consumable with no price on the rule, since fixed needs its price", () => {
    const out = toBody(draft({ sale: "", consumable: true }), TODAY);
    expect(!isError(out) && out.body).toMatchObject({ sale_mode: "rule", consumable: true, fixed_price: null });
  });

  it("drops empty rows and refuses a row without a valid cost", () => {
    const empty = blankRow();
    const named = { ...blankRow(), name: "ספק ג׳" };
    expect(toBody(draft({ rows: [empty] }), TODAY)).toMatchObject({ body: { suppliers: [] } });
    expect(toBody(draft({ rows: [named] }), TODAY)).toMatchObject({ field: "rows", row: named.key });
    expect(toBody(draft({ rows: [{ ...named, cost: "50", lead: "x" }] }), TODAY)).toMatchObject({ field: "rows" });
  });

  it("allows one cost with no supplier and no supplier twice", () => {
    const manual = () => ({ ...blankRow(), cost: "10" });
    expect(toBody(draft({ rows: [manual(), manual()] }), TODAY)).toMatchObject({
      message: "רק עלות אחת יכולה להיות בלי ספק",
    });
    const a = () => ({ ...blankRow(), name: "ספק א׳", cost: "10" });
    expect(toBody(draft({ rows: [a(), a()] }), TODAY)).toMatchObject({ message: "אותו ספק מופיע פעמיים" });
  });

  it("keeps an untouched row as it was, and dates a typed cost today as a manual entry", () => {
    const saved = row({ id: "psp_1", valid_until: "2026-12-31" });
    const p = product({ suppliers: [saved] });
    const untouched = toBody(draftOf(p, {}), TODAY);
    expect(!isError(untouched) && untouched.body.suppliers?.[0]).toEqual({
      id: "psp_1",
      supplier_id: "sup_a",
      supplier_name: null,
      supplier_sku: null,
      unit_cost: "138",
      currency: "ILS",
      lead_days: 2,
      price_date: "2026-10-01",
      valid_until: "2026-12-31",
      preferred: true,
      source: "supplier_price_list",
    });

    const d = draftOf(p, {});
    const typed = toBody({ ...d, rows: d.rows.map((r) => ({ ...r, cost: "1380" })) }, TODAY);
    expect(!isError(typed) && typed.body.suppliers?.[0]).toMatchObject({
      unit_cost: "1380",
      price_date: TODAY,
      valid_until: null,
      source: "manual_entry",
    });
  });

  it("sends a renamed supplier by name, which finds or adds it", () => {
    const d = draftOf(product(), {});
    const out = toBody({ ...d, rows: d.rows.map((r) => ({ ...r, name: "ספק ד׳" })) }, TODAY);
    expect(!isError(out) && out.body.suppliers?.[0]).toMatchObject({ supplier_id: null, supplier_name: "ספק ד׳" });
  });

  it("sends money as strings, never numbers", () => {
    const out = toBody(draft({ sale: "130.50", rows: [{ ...blankRow(), name: "ספק", cost: "96" }] }), TODAY);
    if (isError(out)) throw new Error(out.message);
    expect(out.body.fixed_price).toBe("130.50");
    expect(typeof out.body.suppliers?.[0]?.unit_cost).toBe("string");
  });

  it("sends includes only for a cabinet", () => {
    const out = toBody(draft({ includes: { busbar: true } }), TODAY);
    expect(!isError(out) && out.body.includes).toBeNull();
    const cabinet = toBody(draft({ family: "enclosure", includes: { busbar: true } }), TODAY);
    expect(!isError(cabinet) && cabinet.body.includes).toEqual({ busbar: true });
  });
});

describe("history, drafts and the toast", () => {
  const names = new Map([["sup_a", "ספק א׳"]]);
  const h = (over: Partial<History>): History => ({
    id: "prh_1",
    field: "supplier",
    old: null,
    new: null,
    quote_id: null,
    changed_by: null,
    changed_at: "2026-11-03T08:00:00Z",
    ...over,
  });

  it("writes each change as the prototype does", () => {
    expect(historyText(h({ field: "created", new: { source: "manual_entry" } }), names)).toBe("נוצר ידנית");
    expect(historyText(h({ field: "fixed_price", old: { value: "185" }, new: { value: "195" } }), names)).toBe(
      "מחיר מכירה ₪185 ← ₪195",
    );
    expect(historyText(h({ new: { supplier_id: "sup_a", unit_cost: "138" } }), names)).toBe("נוסף ספק: ספק א׳, ₪138");
    expect(historyText(h({ old: { supplier_id: "sup_gone" } }), names)).toBe("הוסר ספק: ספק");
    expect(
      historyText(
        h({ old: { supplier_id: null, unit_cost: "10" }, new: { supplier_id: null, unit_cost: "12" } }),
        names,
      ),
    ).toBe("עלות ידנית ₪10 ← ₪12");
    expect(historyText(h({ field: "consumable", new: { value: true } }), names)).toBe("סומן כחומר עזר");
    expect(historyText(h({ field: "brand", new: { value: "ABB" } }), names)).toBe("עודכן: יצרן");
  });

  it("names the drafts that use the product", () => {
    expect(draftsText(product())).toBeNull();
    const one = product({ used_in_drafts: [{ quote_id: "quo_1", quote_name: "NURSERY", lines: ["F1, F2", "Q0"] }] });
    expect(draftsText(one)).toBe("בשימוש בטיוטה הפתוחה NURSERY (F1, F2 · Q0)");
  });

  it("says a sent quote didn't change only when the price did", () => {
    const before = product();
    expect(savedText(null, before)).toBe("המוצר נוסף למחירון");
    expect(savedText(before, product())).toBe("נשמר");
    expect(savedText(before, product({ unit_price: "195.0000" }))).toBe("נשמר. הצעות שנשלחו לא השתנו");
  });
});
