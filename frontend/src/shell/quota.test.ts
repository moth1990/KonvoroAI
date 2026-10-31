import { describe, expect, it } from "vitest";

import type { Quota } from "../api/client";
import { FULL_BANNER, quotaView } from "./quota";

type Counter = Quota["counters"][number];

function quota(c: Partial<Counter>, month = "2026-10-01"): Quota {
  const base: Counter = { counter: "quote", limit: 50, used: 0, reserved: 0, extra: 0, remaining: 50, state: "ok" };
  return { month, counters: [{ ...base, ...c }] };
}

describe("quotaView", () => {
  it("under the threshold: a plain meter and no banner", () => {
    expect(quotaView(quota({ used: 12, remaining: 38 }))).toEqual({
      label: "12 מתוך 50",
      pct: 24,
      tone: "ok",
      blocked: false,
      remaining: 38,
      banner: null,
      renews: "1.11",
    });
  });

  it("exactly 80% is still ok: the server's state decides, and near is strictly above 80% (01 §4.5)", () => {
    const view = quotaView(quota({ used: 40, remaining: 10, state: "ok" }));
    expect([view.tone, view.banner]).toEqual(["ok", null]);
  });

  it("near: amber meter and the remaining count in the banner", () => {
    const view = quotaView(quota({ used: 43, remaining: 7, state: "quota_near" }));
    expect([view.pct, view.tone, view.blocked, view.banner]).toEqual([86, "warn", false, "נותרו 7 הצעות החודש"]);
  });

  it("one left reads in the singular", () => {
    expect(quotaView(quota({ used: 49, remaining: 1, state: "quota_near" })).banner).toBe("נותרה הצעה אחת החודש");
  });

  it("reached: new quote is blocked and the banner says why", () => {
    const view = quotaView(quota({ used: 50, remaining: 0, state: "quota_reached" }));
    expect([view.pct, view.tone, view.blocked, view.banner]).toEqual([100, "full", true, FULL_BANNER]);
  });

  it("reserved uploads and one-off extra quota count, like the server's check", () => {
    const view = quotaView(quota({ used: 40, reserved: 4, extra: 5, remaining: 11 }));
    expect([view.label, view.pct]).toEqual(["44 מתוך 55", 80]);
  });

  it("the meter never overflows", () => {
    expect(quotaView(quota({ used: 60, remaining: 0, state: "quota_reached" })).pct).toBe(100);
  });

  it("an unlimited plan shows the count with no meter and is never blocked", () => {
    const view = quotaView(quota({ limit: null, used: 12, remaining: null }));
    expect(view).toMatchObject({ label: "12 הצעות", pct: null, blocked: false, banner: null });
  });

  it("the counter starts again on the first of next month, December rolling to January", () => {
    expect(quotaView(quota({}, "2026-12-01")).renews).toBe("1.1");
  });
});
