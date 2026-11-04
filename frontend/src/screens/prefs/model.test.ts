import { describe, expect, it } from "vitest";

import { rcd30, withRcd30 } from "./model";

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
