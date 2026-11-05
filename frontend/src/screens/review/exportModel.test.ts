import { describe, expect, it } from "vitest";

import type { CustomerDocument } from "../../api/client";
import { documentRows, exportFileName, unpricedText, versionLabel } from "./exportModel";

const row = (description: string, line_total: string | null) => ({
  description,
  sku: null,
  qty: "1.000",
  unit_price: line_total,
  line_total,
});
const totals = {
  price_total: "100.0000",
  discount_pct: null,
  discount: null,
  net_total: "100.0000",
  vat_rate: "0.18",
  vat: "18.00",
  gross_total: "118.0000",
};
const doc = (sections: CustomerDocument["sections"]): CustomerDocument => ({
  name: "NURSERY",
  drawing_number: "26/952",
  customer: null,
  version: 1,
  draft: true,
  quote_date: null,
  company: "לוחות דמו",
  show_sku: false,
  sections,
  totals,
  unpriced_count: 0,
});

describe("the export modal (13 §4.1, S26)", () => {
  it("lists one panel's rows with no heading, and several panels under their names", () => {
    const one = doc([{ name: "NURSERY", rows: [row("a", "1"), row("b", null)], total: "1" }]);
    expect(documentRows(one).map((r) => r.kind)).toEqual(["row", "row"]);
    const two = doc([
      { name: "לוח 1", rows: [row("a", "1")], total: "1" },
      { name: "לוח 2", rows: [row("b", "2")], total: "2" },
    ]);
    expect(documentRows(two).map((r) => (r.kind === "panel" ? `# ${r.name}` : r.row.description))).toEqual([
      "# לוח 1",
      "a",
      "# לוח 2",
      "b",
    ]);
  });

  it("names a version by its number and status", () => {
    const v = { version: 2, status: "draft" as const, quote_date: null, sent_at: null, current: true };
    expect(versionLabel(v)).toBe("גרסה 2 · טיוטה");
    expect(versionLabel({ ...v, version: 1, status: "sent", current: false })).toBe("גרסה 1 · נשלחה");
  });

  it("warns about the unpriced rows as the prototype does", () => {
    expect(unpricedText(5)).toBe("5 שורות בלי מחיר יופיעו במסמך בלי סכום.");
    expect(unpricedText(1)).toBe("שורה אחת בלי מחיר תופיע במסמך בלי סכום.");
  });

  it("names the file as the server does, if its header is lost", () => {
    expect(exportFileName("NURSERY", 2, "pdf")).toBe("הצעת מחיר NURSERY גרסה 2.pdf");
    expect(exportFileName("NURSERY", 2, "xlsx")).toBe("הצעה פנימית NURSERY גרסה 2.xlsx");
  });
});
