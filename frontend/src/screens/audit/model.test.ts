import { describe, expect, it } from "vitest";

import type { Audit, AuditDifference, AuditLine } from "../../api/client";
import {
  auditStartState,
  correctedText,
  coversSeveral,
  decisionText,
  firstBoxPage,
  groups,
  headline,
  kpis,
  moneyText,
  qtyText,
  quoteCheck,
  shortUnits,
  title,
  whereText,
} from "./model";

function diff(over: Partial<AuditDifference> = {}): AuditDifference {
  return {
    diff_id: `dif_${Math.random()}`,
    type: "missing_in_quote",
    severity: "high",
    confidence: 0.9,
    shown: true,
    family: "contactor",
    designators: [],
    drawing_qty: "1.000",
    quote_qty: null,
    quote_line_index: null,
    evidence: [],
    suggested_line: null,
    message: "חסר",
    amount: null,
    status: "open",
    reject_reason: null,
    reject_note: null,
    component_ids: [],
    boxes: [],
    ...over,
  };
}

function line(over: Partial<AuditLine> = {}): AuditLine {
  return {
    index: 1,
    description: 'מא"ז 3X16A',
    qty: "1.000",
    unit_price: "185.0000",
    total: "185.0000",
    confidence: 0.95,
    page_no: 1,
    status: "matched",
    includes: [],
    component_ids: [],
    designators: [],
    matched_qty: "1",
    ...over,
  };
}

function audit(differences: AuditDifference[], summary: Partial<NonNullable<Audit["summary"]>> = {}): Audit {
  return {
    audit_id: "aud_1",
    drawing_id: "drw_1",
    status: "ready",
    drawing_status: "ready",
    drawing_name: "MAIN ELECTRICAL BOARD",
    drawing_file_name: "MAIN_ELECTRICAL_BOARD.pdf",
    drawing_number: "26/993",
    quote_file_name: "Hatzaa_10271.pdf",
    input_kind: "factory_drawing",
    quote_ref: { number: "10271", date: null, total_before_vat: "14022.00" },
    summary: {
      quote_lines: 17,
      lines_matched: 15,
      drawing_components: 22,
      differences: differences.length,
      info_notes: 0,
      missing_items: 6,
      value_at_risk: "0.00",
      missing_items_without_price: 0,
      over_charged: "0.00",
      not_differences: 0,
      to_check: 0,
      ...summary,
    },
    issues: [],
    lines: [line({ index: 16, description: "מפסק 4X125A", status: "quantity_differs" })],
    differences,
    corrected_quote_id: null,
    pages: [],
  };
}

// 26-993 as the factory confirmed it (prototype `vAudit`): QG2 short, the shunt trips and the CTs missing.
const QG = diff({
  type: "qty_short",
  drawing_qty: "2.000",
  quote_qty: "1.000",
  amount: "1250.0000",
  quote_line_index: 16,
  designators: ["QG1", "QG2"],
});
const TC = diff({ drawing_qty: "2.000", designators: ["TC-G1", "TC-G2"] });
const MS = diff({ drawing_qty: "3.000", designators: ["MS1", "MS2", "MS3"] });
const TERMINALS = diff({ type: "not_a_difference", severity: "info", drawing_qty: "6.000" });

describe("the audit's numbers", () => {
  it("counts a short quantity as an omission, as the prototype counts 10271's three (S16 decision 3)", () => {
    const k = kpis(audit([QG, TC, MS, TERMINALS], { value_at_risk: "1250.00" }));
    expect(k).toEqual({ matched: "15 / 17", omissions: 3, units: 6, atRisk: "₪1,250", unpriced: 5, notDifferences: 1 });
  });

  it("leaves the ones to check out of every number", () => {
    const k = kpis(audit([QG, diff({ shown: false, confidence: 0.49, drawing_qty: "2.000" })]));
    expect([k.omissions, k.units]).toEqual([1, 1]);
  });

  it("short units never go below zero", () => {
    expect(shortUnits(diff({ type: "qty_short", drawing_qty: "1.000", quote_qty: "3.000" }))).toBe(0);
    expect(shortUnits(diff({ type: "qty_over" }))).toBe(0);
  });
});

describe("the headline (11 §7)", () => {
  it("says the omissions, the money and the items without a price", () => {
    expect(headline(audit([QG, TC, MS, TERMINALS], { value_at_risk: "1250.00" }))).toBe(
      "נמצאו 3 הבדלים: 6 רכיבים חסרים. כסף בסיכון: ₪1,250, ועוד 5 רכיבים בלי מחיר.",
    );
  });

  it("joins a double count with Hebrew's and, as the spec's NEVIS-1 example reads", () => {
    const missing = Array.from({ length: 4 }, () => diff({ drawing_qty: "3.000" }));
    const double = diff({ type: "possible_double_count", severity: "medium", amount: "-42.0000" });
    expect(headline(audit([...missing, double], { value_at_risk: "140.00", over_charged: "42.00" }))).toBe(
      "נמצאו 5 הבדלים: 12 רכיבים חסרים, ורכיב אחד שנספר פעמיים. כסף בסיכון: ₪140, ועוד 12 רכיבים בלי מחיר. נגבה ביותר: ₪42.",
    );
  });

  it("has nothing at risk when no omission has a price", () => {
    expect(headline(audit([TC]))).toBe("נמצא הבדל אחד: 2 רכיבים חסרים. ל-2 רכיבים אין מחיר דומה בהצעה.");
  });

  it("says when nothing was found, and what is left to check", () => {
    expect(headline(audit([]))).toBe("לא נמצאו הבדלים בין ההצעה לשרטוט.");
    expect(headline(audit([diff({ shown: false })]))).toBe("לא נמצאו הבדלים בין ההצעה לשרטוט. הבדל אחד לבדוק.");
  });

  it("counts other kinds apart", () => {
    const extra = diff({ type: "attribute_mismatch", amount: "20.0000" });
    expect(headline(audit([TC, extra], { value_at_risk: "20.00" }))).toBe(
      "נמצאו 2 הבדלים: 2 רכיבים חסרים, והבדל אחר. כסף בסיכון: ₪20, ועוד 2 רכיבים בלי מחיר.",
    );
  });
});

describe("grouping", () => {
  it("puts information after the differences, and anything below 0.6 apart", () => {
    const low = diff({ shown: false, type: "extra_in_quote" });
    const lowInfo = diff({ shown: false, type: "not_a_difference" });
    const g = groups([QG, TERMINALS, low, TC, lowInfo]);
    expect(g.shown).toEqual([QG, TC]);
    expect(g.info).toEqual([TERMINALS]);
    expect(g.toCheck).toEqual([low, lowInfo]);
  });
});

describe("a difference's row", () => {
  it("is named by its suggested line, else the quote's line, else its message", () => {
    const a = audit([]);
    expect(
      title(
        diff({ suggested_line: { description: "מגען 3P", qty: "3", unit_price: null, price_source: null } }),
        a.lines,
      ),
    ).toBe("מגען 3P");
    expect(title(QG, a.lines)).toBe("מפסק 4X125A");
    expect(title(diff({ message: "שורה 13 בהצעה" }), a.lines)).toBe("שורה 13 בהצעה");
    const aux = diff({ message: "מהדק × 16 (C, COM, EM1): חומר עזר בהגדרות המפעל, ולכן לא הבדל" });
    expect(title(aux, a.lines)).toBe("מהדק");
  });

  it("reads quantities as whole units, and none as a dash", () => {
    expect([qtyText("2.000"), qtyText("1.500"), qtyText(null), qtyText("0.000")]).toEqual(["2", "1.5", "—", "—"]);
  });

  it("says the money: at risk, over-charged, or why there is none", () => {
    expect(moneyText(QG)).toEqual({ text: "₪1,250", muted: false });
    expect(moneyText(diff({ type: "qty_over", amount: "-42.0000" }))).toEqual({ text: "נגבה ביותר ₪42", muted: false });
    expect(moneyText(TC)).toEqual({ text: "אין מחיר דומה", muted: true });
    expect(moneyText(TERMINALS)).toEqual({ text: "—", muted: true });
  });

  it("says where: the pages, or the quote's line", () => {
    const ev = (n: number) => ({ page_no: n, instance_ids: [] });
    expect(whereText(diff({ evidence: [ev(3)] }))).toBe("עמוד 3");
    expect(whereText(diff({ evidence: [ev(5), ev(3), ev(5)] }))).toBe("עמודים 3, 5");
    expect(whereText(diff({ quote_line_index: 13 }))).toBe("שורה 13 בהצעה");
    expect(whereText(diff())).toBe("");
  });

  it("says the decision and its reason", () => {
    expect(decisionText(QG)).toBeNull();
    expect(decisionText(diff({ status: "confirmed" }))).toBe("אושר");
    expect(decisionText(diff({ status: "rejected", reject_reason: "customer_supplies" }))).toBe("נדחה: הלקוח מספק");
    expect(decisionText(diff({ status: "rejected" }))).toBe("נדחה");
  });

  it("opens the drawing on the first page it is boxed on", () => {
    const pages = [
      { page_id: "pg_a", page_no: 1 },
      { page_id: "pg_b", page_no: 3 },
    ] as Audit["pages"];
    const boxed = diff({
      boxes: [
        { page_id: "pg_b", bbox: [0, 0, 1, 1] },
        { page_id: "pg_a", bbox: [0, 0, 1, 1] },
      ],
    });
    expect(firstBoxPage(boxed, pages)).toBe("pg_a");
    expect(firstBoxPage(diff(), pages)).toBeNull();
  });
});

describe("the quote's lines and the corrected quote", () => {
  it("marks a line that covers several devices", () => {
    expect(coversSeveral(line({ description: "ארון 1000/800/300 כולל פסי צבירה" }))).toBe(true);
    expect(coversSeveral(line({ description: "מנתק נתיך גלילי +נתיכים" }))).toBe(true);
    expect(coversSeveral(line({ includes: ["פסי צבירה"] }))).toBe(true);
    expect(coversSeveral(line())).toBe(false);
  });

  it("says what the corrected quote holds (prototype toast)", () => {
    expect(correctedText(audit([{ ...QG, status: "confirmed" }, { ...TC, status: "confirmed" }, MS]))).toBe(
      "נוצרה טיוטה מתוקנת: שורה אחת + 2 חסרות",
    );
    expect(correctedText(audit([QG]))).toBe("נוצרה טיוטה מתוקנת: שורה אחת");
  });
});

describe("the upload's start bar", () => {
  const file = (name: string) => ({ key: name, file: new File(["x"], name), error: quoteCheck({ name, size: 1 }) });

  it("needs both sides, and refuses a ZIP quote", () => {
    expect(auditStartState({ drawings: [], quote: null, remaining: 5, busy: false }).text).toBe("בחרו את השרטוט");
    expect(auditStartState({ drawings: [file("a.pdf")], quote: null, remaining: 5, busy: false }).text).toBe(
      "בחרו את ההצעה הקיימת",
    );
    const zip = file("q.zip");
    expect(zip.error?.code).toBe("quote_not_one_file");
    expect(auditStartState({ drawings: [file("a.pdf")], quote: zip, remaining: 5, busy: false }).canStart).toBe(false);
  });

  it("says the quota, and waits while uploading", () => {
    const ok = { drawings: [file("a.pdf")], quote: file("q.xlsx") };
    expect(auditStartState({ ...ok, remaining: 38, busy: false })).toEqual({
      text: "ייספר 1 מהמכסה (נותרו 38) רק אם הקליטה מצליחה",
      isError: false,
      canStart: true,
    });
    expect(auditStartState({ ...ok, remaining: null, busy: true }).canStart).toBe(false);
    expect(auditStartState({ ...ok, remaining: 0, busy: false }).isError).toBe(true);
  });
});
