import { describe, expect, it } from "vitest";

import { line, panel, quote, red } from "./fixtures";
import {
  buildRows,
  compactDesignators,
  filterCounts,
  matches,
  nextFilter,
  panelTabs,
  percent,
  priceSourceText,
  progress,
  qtyText,
  qtyTimesPrice,
  reasonChips,
  shekels,
  sourceText,
  statusMark,
  stepLine,
} from "./model";

describe("money from strings", () => {
  it.each([
    ["4674.0000", "₪4,674"],
    ["24.575", "₪24.58"],
    ["24.574", "₪24.57"],
    ["0.0000", "₪0"],
    ["1250", "₪1,250"],
    ["-337.11", "-₪337.11"],
    ["-0.001", "₪0"],
    ["2210.0000000", "₪2,210"],
    ["1234567.995", "₪1,234,568"],
  ])("%s → %s", (amount, text) => {
    expect(shekels(amount)).toBe(text);
  });

  it("shows a dash when there is no price", () => {
    expect(shekels(null)).toBe("—");
    expect(shekels(undefined)).toBe("—");
  });

  it("formats rates and quantities", () => {
    expect(percent("0.2756")).toBe("28%");
    expect(percent("0.2733")).toBe("27%");
    expect(percent("0.18")).toBe("18%");
    expect(percent("-0.05")).toBe("-5%");
    expect(percent(null)).toBe("—");
    expect(qtyText("17.000")).toBe("17");
    expect(qtyText("2.500")).toBe("2.5");
    expect(qtyText("4")).toBe("4");
    expect(qtyTimesPrice(line({ qty: "4.000", unit_price: "24.5800" }))).toBe("4 × ₪24.58");
  });
});

describe("filters (09 §6.2)", () => {
  const lines = [
    line({ status: "green" }),
    line({ status: "yellow" }),
    line({ status: "red" }),
    line({ status: "red" }),
  ];

  it("counts each filter", () => {
    expect(filterCounts(lines)).toEqual({ all: 4, review: 3, green: 1, yellow: 1, red: 2 });
  });

  it("review only hides green", () => {
    expect(lines.filter((l) => matches(l, "review")).map((l) => l.status)).toEqual(["yellow", "red", "red"]);
    expect(lines.filter((l) => matches(l, "all"))).toHaveLength(4);
  });

  it("a second click on the active filter goes back to all", () => {
    expect(nextFilter("all", "red")).toBe("red");
    expect(nextFilter("red", "red")).toBe("all");
    expect(nextFilter("red", "yellow")).toBe("yellow");
    expect(nextFilter("all", "all")).toBe("all");
  });

  it("progress counts green as ready", () => {
    expect(progress(lines)).toEqual({ ready: 1, total: 4, text: "1 מתוך 4 שורות מוכנות", pct: 25 });
    expect(progress([]).pct).toBe(0);
  });
});

describe("panel tabs (S09 decision 10)", () => {
  it("are hidden for one panel", () => {
    expect(panelTabs(quote([panel("NURSERY", [line()])]))).toEqual([]);
  });

  it("count each panel's non-green lines", () => {
    const q = quote([
      panel("לוח ראשי", [line({ status: "red" }), line({ status: "yellow" }), line()]),
      panel("לוח קומה 2", [line()]),
    ]);
    expect(panelTabs(q).map((t) => [t.name, t.open])).toEqual([
      ["לוח ראשי", 2],
      ["לוח קומה 2", 0],
    ]);
  });
});

describe("rows (09 §6.3)", () => {
  const q0 = line({ line_group: "feed", status: "red", description: "Q0" });
  const kit = line({ line_group: "feed", parent_line_id: q0.line_id, included: true, description: "kit" });
  const f1 = line({ line_group: "outputs", description: "F1" });
  const enc = line({ line_group: "enclosure", status: "red", description: "enc" });
  const miss = line({ line_type: "missing", section: "missing", line_group: null, status: "red", description: "?" });
  const busbar = line({ line_type: "derived", section: "extras", line_group: null, description: "busbar" });
  const labor = line({ line_type: "labor", section: "extras", line_group: null, description: "labor" });
  const p = panel("NURSERY", [q0, kit, f1, enc, miss, busbar, labor], "4674.0000");

  it("puts a header where the group or section changes and ends with the panel total", () => {
    const rows = buildRows(p, "all");
    const text = rows.map((r) =>
      r.kind === "group" ? `# ${r.label}` : r.kind === "line" ? `${r.child ? "  " : ""}${r.line.description}` : r.kind,
    );
    expect(text).toEqual([
      "# הזנה",
      "Q0",
      "  kit",
      "# יציאות",
      "F1",
      "# ארון",
      "enc",
      "# רכיבים שלא זוהו",
      "?",
      "# פריטים נלווים ועבודה",
      "busbar",
      "labor",
      "total",
    ]);
    const total = rows.at(-1);
    expect(total?.kind === "total" && [total.label, total.amount]).toEqual(["סה״כ NURSERY לפני מע״מ", "4674.0000"]);
  });

  it("drops what the filter hides, and headers with nothing under them", () => {
    const rows = buildRows(p, "red");
    expect(rows.filter((r) => r.kind === "group").map((r) => r.kind === "group" && r.label)).toEqual([
      "הזנה",
      "ארון",
      "רכיבים שלא זוהו",
    ]);
  });

  it("shows the empty state when nothing matches, and still the total", () => {
    const rows = buildRows(panel("x", [line()]), "yellow");
    expect(rows.map((r) => r.kind)).toEqual(["empty", "total"]);
  });

  it("names an ungrouped component section", () => {
    const rows = buildRows(panel("x", [line({ line_group: null })]), "all");
    expect(rows[0]).toMatchObject({ kind: "group", label: "רכיבים" });
  });
});

describe("keyboard steps (09 §8)", () => {
  const ids = ["a", "b", "c"];
  it("moves within the shown lines and stops at the ends", () => {
    expect(stepLine(ids, null, 1)).toBe("a");
    expect(stepLine(ids, null, -1)).toBe("c");
    expect(stepLine(ids, "a", 1)).toBe("b");
    expect(stepLine(ids, "c", 1)).toBe("c");
    expect(stepLine(ids, "a", -1)).toBe("a");
    expect(stepLine(ids, "gone", 1)).toBe("a");
    expect(stepLine([], "a", 1)).toBeNull();
  });
});

describe("status shape and chips (09 §6.3, §9, §13)", () => {
  it("maps each color to a shape and a spoken label", () => {
    expect(statusMark(line({ status: "green" }))).toEqual({ shape: "check", label: "בטוח" });
    expect(statusMark(line({ status: "yellow" }))).toEqual({ shape: "triangle", label: "לבדיקה" });
    expect(statusMark(line({ status: "red" }))).toEqual({ shape: "cross", label: "לא זוהה או שגוי" });
    expect(statusMark(line({ line_type: "derived" }))).toEqual({ shape: "box", label: "פריט נלווה · בטוח" });
    expect(statusMark(line({ line_type: "labor", status: "red" })).shape).toBe("box");
  });

  it("shows every reason, not only the worst", () => {
    const l = line({
      status: "yellow",
      status_reasons: [
        { source: "confidence", status: "yellow", value: 0.71, issue_id: null },
        { source: "match", status: "yellow", value: { code: "defaulted_attribute", value: "6kA" }, issue_id: null },
        {
          source: "match",
          status: "yellow",
          value: { code: "brand_substituted", drawing: "ABB", chosen: "שניידר" },
          issue_id: null,
        },
        { source: "price", status: "yellow", value: "stale", issue_id: null },
      ],
    });
    expect(reasonChips(l, []).map((c) => c.text)).toEqual([
      "ביטחון קריאה 0.71",
      "6kA: ברירת מחדל",
      "בשרטוט: ABB · נבחר: שניידר",
      "מחיר ישן",
    ]);
  });

  it("words the NURSERY reasons as the prototype does", () => {
    const q0 = line({
      status: "red",
      status_reasons: [
        { source: "match", status: "green", value: "explicit_model", issue_id: null },
        { source: "match", status: "green", value: "kit", issue_id: null },
        red("missing"),
      ],
    });
    expect(reasonChips(q0, [])).toEqual([
      { text: "דגם מפורש", tone: "acc" },
      { text: "ערכה", tone: "out" },
      { text: "אין מחיר", tone: "bad" },
    ]);
  });

  it("uses the finding's title for a validator reason, and hides info findings", () => {
    const finding = {
      finding_id: "iss_1",
      severity: "warning" as const,
      code: "X",
      title: "זרם גבוה מהמפסק הראשי",
      message: "…",
      line_ids: [],
      page_no: null,
    };
    const warn = line({
      status: "yellow",
      status_reasons: [{ source: "validator", status: "yellow", value: null, issue_id: "iss_1" }],
    });
    expect(reasonChips(warn, [finding])).toEqual([{ text: "זרם גבוה מהמפסק הראשי", tone: "warn" }]);
    expect(reasonChips(warn, [])).toEqual([{ text: "ממצא של הבודק", tone: "warn" }]);
    const info = line({ status_reasons: [{ source: "validator", status: "green", value: null, issue_id: "iss_1" }] });
    expect(reasonChips(info, [finding])).toEqual([]);
  });

  it("explains a missing line, a user's approval and a manual line", () => {
    expect(reasonChips(line({ status: "red", status_reasons: [{ source: "missing", status: "red" }] }), [])).toEqual([
      { text: "רכיב שלא זוהה", tone: "bad" },
    ]);
    expect(reasonChips(line({ status_reasons: [{ source: "user", status: "green", value: "approved" }] }), [])).toEqual(
      [{ text: "אושר", tone: "ok" }],
    );
    expect(reasonChips(line({ status_reasons: [{ source: "user", status: "green", value: "manual" }] }), [])).toEqual([
      { text: "נוסף ידנית", tone: "ok" },
    ]);
  });

  it("never leaves a yellow or red line without a chip", () => {
    const silent = line({ status: "red", status_reasons: [{ source: "something_new", status: "red" }] });
    expect(reasonChips(silent, [])).toEqual([{ text: "לא זוהה או שגוי", tone: "bad" }]);
    const greenOnly = line({
      status: "yellow",
      status_reasons: [{ source: "match", status: "green", value: "explicit_model" }],
    });
    expect(reasonChips(greenOnly, []).map((c) => c.text)).toEqual(["דגם מפורש", "לבדיקה"]);
    expect(reasonChips(line(), [])).toEqual([]);
  });
});

describe("line detail wording (09 §6.4)", () => {
  const src = (source: string, detail: string | null = null, confidence: number | null = 0.95) => ({
    attribute: "current",
    value: "16A",
    source,
    detail,
    confidence,
  });

  it.each([
    [src("drawing"), "שרטוט", false],
    [src("drawing", '"3X6A"'), 'שרטוט, ‏"3X6A"', false],
    [src("circuit", "F22–F25 (3X16A)"), "הוסק מ-F22–F25 (3X16A)", true],
    [src("notes", "עמוד 1"), "עמוד 1", false],
    [src("notes"), "מההערות הכלליות", false],
    [src("tenant_default"), "לא כתוב בשרטוט. ברירת מחדל של המפעל", true],
    [src("memory", "הצעה 10288"), "זיכרון התאמות, ‏הצעה 10288", false],
    [src("missing", null, null), "לא נמצא בשרטוט", true],
    [src("drawing", null, 0.71), "נקרא ב-OCR (ביטחון 0.71)", true],
    [src("brand_new_source"), "brand_new_source", false],
  ])("%o", (s, text, warn) => {
    expect(sourceText(s)).toEqual({ text, warn });
  });

  it("names where the sale price comes from", () => {
    expect(priceSourceText(line())).toBe("הצעה 10288");
    expect(priceSourceText(line({ price_source: { kind: "fixed", quotes: ["10288", "10271"] } }))).toBe(
      "הצעות 10288, 10271",
    );
    expect(priceSourceText(line({ price_source: { kind: "markup", quotes: [], value: "0.25" } }))).toBe("חוק רווח 25%");
    expect(priceSourceText(line({ price_source: null }))).toBe("הוזן ידנית");
    expect(priceSourceText(line({ price_source: { kind: "manual", quotes: [] } }))).toBe("הוזן ידנית");
  });

  it("compacts runs of tags", () => {
    const f = Array.from({ length: 17 }, (_, i) => `F${i + 1}`);
    expect(compactDesignators(f)).toEqual(["F1–F17"]);
    expect(compactDesignators(["F22", "F23", "F24", "F25", "F30"])).toEqual(["F22–F25", "F30"]);
    expect(compactDesignators(["L1", "L2", "L3", "HNV"])).toEqual(["L1–L3", "HNV"]);
    expect(compactDesignators(["Q0"])).toEqual(["Q0"]);
    expect(compactDesignators(["F1", "F2"])).toEqual(["F1", "F2"]);
    expect(compactDesignators(["Q0b", "ארון"])).toEqual(["Q0b", "ארון"]);
  });
});
