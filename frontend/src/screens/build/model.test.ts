import { describe, expect, it } from "vitest";

import type { Build, BuildMessage } from "../../api/client";
import { line, panel, quote } from "../review/fixtures";
import { draftCounts, draftRows, draftTotal, droppedText, extras, pending, shownMessages, understood } from "./model";

function message(over: Partial<BuildMessage> = {}): BuildMessage {
  return {
    message_id: "bmg_1",
    role: "user",
    text: "",
    heard: null,
    status: "applied",
    created_at: "2026-11-06T08:00:00Z",
    items: [],
    changes: [],
    dropped: [],
    question: null,
    ...over,
  };
}

function build(messages: BuildMessage[]): Build {
  return { drawing_id: "drw_1", quote_id: null, messages, quote: null, can_undo: false, voice_stand_in: true };
}

describe("the draft's rows", () => {
  const q = quote([
    panel("לוח 1", [
      line({ line_id: "ln_a", description: 'מא"ז 1P 16A', qty: "12.000", unit_price: "42.00", line_total: "504.00" }),
      line({ line_id: "ln_b", description: "מפסק 4P 63A", unit_price: null, line_total: null, status: "red" }),
      line({ line_id: "ln_c", description: "ארון", line_type: "derived", section: "extras", line_total: "850.00" }),
      line({ line_id: "ln_d", description: "עבודה", line_type: "labor", section: "extras", line_total: "120.50" }),
    ]),
  ]);

  it("lists what the estimator described, not the extras", () => {
    expect(draftRows(q).map((r) => r.line.line_id)).toEqual(["ln_a", "ln_b"]);
    expect(draftRows(q).map((r) => r.priced)).toEqual([true, false]);
  });

  it("sums the extras into one row", () => {
    expect(extras(q)).toEqual({ count: 2, total: "970.50" });
    expect(extras(null)).toEqual({ count: 0, total: null });
  });

  it("counts the rows and the unpriced ones (prototype line 1348)", () => {
    expect(draftCounts(draftRows(q))).toBe("2 שורות · 1 בלי מחיר");
    expect(draftCounts(draftRows(q).slice(0, 1))).toBe("שורה אחת");
  });

  it("names the panel only when there are several", () => {
    const two = quote([panel("לוח 1", [line()]), panel("לוח 2", [line({ line_id: "ln_z" })])]);
    expect(draftRows(two).map((r) => r.panel)).toEqual(["לוח 1", "לוח 2"]);
    expect(draftRows(q).every((r) => r.panel === null)).toBe(true);
  });

  it("totals before VAT", () => {
    expect(draftTotal(null)).toBe("₪0");
  });
});

describe("what a message was understood as", () => {
  const m = message({
    items: [
      { text: 'מא"ז 1X16A', quantity: 12, panel: null },
      { text: "פחת 4X40A", quantity: 1, panel: "לוח 2" },
    ],
    changes: [
      { line_id: "ln_a", description: "מגען 3P 25A", action: "set_qty", quantity: 10 },
      { line_id: "ln_b", description: "מפסק פחת", action: "remove", quantity: null },
      { line_id: "ln_c", description: "נורית", action: "add_qty", quantity: 2 },
    ],
    dropped: [{ quote: "פחת 4X40 30mA", reason: "number_not_said" }],
  });

  it("one line for each item and change", () => {
    expect(understood(m)).toEqual([
      '12 × מא"ז 1X16A',
      "פחת 4X40A (לוח 2)",
      "מגען 3P 25A: כמות 10",
      "להסיר: מפסק פחת",
      "נורית: עוד 2",
    ]);
  });

  it("says why something was left out", () => {
    expect(droppedText(m)).toEqual(['"פחת 4X40 30mA": יש בו ערך שלא נאמר']);
  });
});

describe("the conversation", () => {
  it("finds the recording that waits, and hides one sent back to the input", () => {
    const b = build([
      message({ message_id: "bmg_1" }),
      message({ message_id: "bmg_2", status: "dismissed", heard: "שמונה" }),
      message({ message_id: "bmg_3", status: "pending", heard: "ארבעה מגענים" }),
    ]);
    expect(pending(b)?.message_id).toBe("bmg_3");
    expect(shownMessages(b).map((x) => x.message_id)).toEqual(["bmg_1", "bmg_3"]);
    expect(pending(build([message()]))).toBeNull();
  });
});
