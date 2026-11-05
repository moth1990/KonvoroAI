import { describe, expect, it } from "vitest";

import type { ChatProposal } from "../../api/client";
import {
  amount,
  applyLabel,
  diffRows,
  optionLabel,
  rememberChoices,
  rememberedText,
  segments,
  STATE,
  totals,
  unchanged,
  warningTexts,
} from "./chatModel";

const money = {
  $T1: { kind: "ils" as const, value: "1250.5" },
  $T2: { kind: "ils" as const, value: "1300" },
  $P1: { kind: "pct" as const, value: "0.2756" },
};

function proposal(over: Partial<ChatProposal> = {}): ChatProposal {
  return {
    proposal_id: "prp_1",
    summary_he: "החלפה",
    status: "pending",
    affected_line_count: 1,
    warnings: [],
    base_version: 1,
    money,
    remember_options: ["quote_only"],
    diff: {
      lines_changed: [
        {
          line_id: "ln_A",
          before: { sku: "S203", manufacturer: "ABB", description: 'מא"ז ABB', qty: "4", unit_price: "$T1" },
          after: { sku: "A9F", manufacturer: "Schneider", description: 'מא"ז Schneider', qty: "4", unit_price: "$T2" },
          note: null,
        },
        {
          line_id: "ln_B",
          before: { sku: "X", description: "מגען", qty: "1" },
          after: { sku: "X", description: "מגען", qty: "1" },
          note: "אין בקטלוג מוצר מתאים",
        },
      ],
      lines_added: [],
      lines_removed: [{ line_id: "ln_C", before: { description: "ממסר", qty: "2" } }],
      derived_changes: [],
      totals_before: { net_total: "$T1" },
      totals_after: { net_total: "$T2" },
      new_issues: ["חסר מחיר"],
      deleted_count: 7,
    },
    ...over,
  };
}

describe("text references", () => {
  it("splits text into chips and amounts", () => {
    expect(segments("ראה {{line:ln_01ABC}} סך {{$T1}}.")).toEqual([
      { kind: "text", text: "ראה " },
      { kind: "line", lineId: "ln_01ABC" },
      { kind: "text", text: " סך " },
      { kind: "money", ref: "$T1" },
      { kind: "text", text: "." },
    ]);
    expect(segments("בלי הפניות")).toEqual([{ kind: "text", text: "בלי הפניות" }]);
  });

  it("formats amounts the server sent, and a dash for one it did not", () => {
    expect(amount(money, "$T1")).toBe("₪1,250.50");
    expect(amount(money, "$P1")).toBe("28%");
    expect(amount(money, "$T9")).toBe("—");
    expect(amount(money, null)).toBe("—");
  });
});

describe("the proposal card", () => {
  it("shows the lines that change, removed lines, and the unchanged ones by reason", () => {
    const rows = diffRows(proposal());
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ lineId: "ln_A", before: 'מא"ז ABB ×4', after: 'מא"ז Schneider ×4' });
    expect(rows[1]).toMatchObject({ lineId: "ln_C", before: "ממסר ×2", after: "נמחק" });
    expect(unchanged(proposal())).toEqual(["שורה אחת לא משתנה: אין בקטלוג מוצר מתאים"]);
  });

  it("shows a price change with its amounts", () => {
    const p = proposal();
    const d = p.diff as { lines_changed: { after: object }[] };
    const first = d.lines_changed[0];
    if (first) first.after = { sku: "S203", manufacturer: "ABB", description: 'מא"ז ABB', qty: "4", unit_price: "$T2" };
    expect(diffRows(p)[0]?.after).toBe('מא"ז ABB ×4 · ₪1,300');
  });

  it("has totals, warnings and the delete button's wording", () => {
    expect(totals(proposal())).toEqual({ before: "₪1,250.50", after: "₪1,300" });
    expect(warningTexts(proposal({ warnings: ["new_issues", "opens_new_version", "unknown"] }))).toEqual([
      "ממצאים חדשים מהבודק: חסר מחיר",
      "ההצעה נשלחה. האישור יפתח גרסה 2",
    ]);
    expect(applyLabel(proposal())).toBe("החל");
    expect(applyLabel(proposal({ warnings: ["many_deletes"] }))).toBe("מחק 7 שורות");
    expect(STATE.expired.text).toBe("פג תוקף");
  });
});

describe("S25b references and memory", () => {
  it("parses another quote and a drawing instance", () => {
    expect(segments("מול {{quote:quo_01AB}} ברכיב {{instance:ins_01CD}} ו-{{instance:ln_01EF#0}}")).toEqual([
      { kind: "text", text: "מול " },
      { kind: "quote", quoteId: "quo_01AB" },
      { kind: "text", text: " ברכיב " },
      { kind: "instance", instanceId: "ins_01CD" },
      { kind: "text", text: " ו-" },
      { kind: "instance", instanceId: "ln_01EF#0" },
    ]);
  });

  it("shows an option's quote by its name, which only the screen has", () => {
    expect(optionLabel("{{quote:quo_01AB}}", { quo_01AB: "גן ילדים, הצעה קודמת" })).toBe("גן ילדים, הצעה קודמת");
    expect(optionLabel("לא, {{quote:quo_01ZZ}}", {})).toBe("לא, הצעה אחרת");
  });

  it("offers the memory chips only beside this quote, in order", () => {
    expect(rememberChoices(proposal())).toEqual([]);
    expect(rememberChoices(proposal({ remember_options: ["tenant", "quote_only"] }))).toEqual(["quote_only", "tenant"]);
    expect(rememberChoices(proposal({ remember_options: ["quote_only", "customer", "tenant"] }))).toEqual([
      "quote_only",
      "customer",
      "tenant",
    ]);
  });

  it("says what an applied card remembered", () => {
    expect(rememberedText(proposal({ status: "applied", remembered: "quote_only" }))).toBeNull();
    expect(rememberedText(proposal({ status: "applied", remembered: "tenant" }))).toContain("המפעל");
    expect(rememberedText(proposal({ status: "applied", remembered: "customer" }))).toContain("הלקוח");
  });
});
