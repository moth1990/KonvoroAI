import { describe, expect, it } from "vitest";

import { documentBody, documentForm, rcd30, sameForm, withRcd30 } from "./model";

describe("the RCD's 30 mA default", () => {
  it("reads the residual current default", () => {
    expect(rcd30({ rcd: { residual_ma: 30 } })).toBe(true);
    expect(rcd30({ rcd: { residual_ma: 300 } })).toBe(false);
    expect(rcd30({})).toBe(false);
  });

  it("turns it on and off and keeps the other defaults", () => {
    const demo = { rcd: { residual_ma: 30, rcd_type: "A" }, circuit_breaker: { curve: "C" } };
    expect(withRcd30(demo, false)).toEqual({ rcd: { rcd_type: "A" }, circuit_breaker: { curve: "C" } });
    expect(withRcd30({ rcd: { residual_ma: 30 } }, false)).toEqual({});
    expect(withRcd30({}, true)).toEqual({ rcd: { residual_ma: 30 } });
    expect(demo.rcd.residual_ma).toBe(30); // not changed in place
  });
});

describe('"המסמך ללקוח" (S26 decision 1)', () => {
  const stored = {
    company: { name: "לוחות דמו", company_id: "510000000", address: null, phone: "03-5550123" },
    terms: null,
    show_sku: false,
    logo_url: null,
  };

  it("turns the template into fields and back, an empty field not set", () => {
    const form = documentForm(stored);
    expect(form).toEqual({
      name: "לוחות דמו",
      company_id: "510000000",
      address: "",
      phone: "03-5550123",
      terms: "",
      show_sku: false,
    });
    expect(documentBody({ ...form, address: "  ", terms: " שוטף + 60 ", show_sku: true })).toEqual({
      company: { name: "לוחות דמו", company_id: "510000000", address: null, phone: "03-5550123" },
      terms: "שוטף + 60",
      show_sku: true,
    });
  });

  it("knows when there is something to save", () => {
    const form = documentForm(stored);
    expect(sameForm(form, documentForm(stored))).toBe(true);
    expect(sameForm({ ...form, show_sku: true }, form)).toBe(false);
  });
});
