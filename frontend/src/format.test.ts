import { describe, expect, it } from "vitest";

import { countText, shekelsFloor, weekdayText, whenText } from "./format";

describe("shekelsFloor", () => {
  it.each([
    ["1250.0000", "₪1,250"],
    ["1290.5000", "₪1,290"],
    ["999.99", "₪999"],
    ["1234567.0000", "₪1,234,567"],
    ["0.40", "₪0"],
    ["0050", "₪50"],
    ["-1250.00", "-₪1,250"],
  ])("%s -> %s, without going through a number", (input, out) => {
    expect(shekelsFloor(input)).toBe(out);
  });

  it("keeps digits a float would lose", () => {
    expect(shekelsFloor("12345678901234567.89")).toBe("₪12,345,678,901,234,567");
  });
});

describe("countText", () => {
  it("one has its own words, the rest use the number", () => {
    const text = (n: number) => countText(n, "מחיר חסר אחד", (k) => `${k} מחירים חסרים`);
    expect([text(1), text(5)]).toEqual(["מחיר חסר אחד", "5 מחירים חסרים"]);
  });
});

describe("dates, in the tenant's timezone", () => {
  // Friday 2026-10-30, 23:30 in Jerusalem (UTC+2 after the October change), still Friday 21:30 UTC.
  const now = new Date("2026-10-30T21:30:00Z");

  it("today shows the time", () => {
    expect(whenText("2026-10-30T07:12:00Z", now, "Asia/Jerusalem")).toBe("היום, 09:12");
  });

  it("yesterday", () => {
    expect(whenText("2026-10-29T10:00:00Z", now, "Asia/Jerusalem")).toBe("אתמול");
  });

  it("older dates are day.month", () => {
    expect(whenText("2026-10-20T10:00:00Z", now, "Asia/Jerusalem")).toBe("20.10");
  });

  it("the day boundary follows the tenant, not UTC", () => {
    // 22:30 UTC on the 30th is already the 31st in Jerusalem.
    const late = new Date("2026-10-30T22:30:00Z");
    expect(whenText("2026-10-30T22:10:00Z", late, "Asia/Jerusalem")).toBe("היום, 00:10");
    expect(weekdayText(late, "Asia/Jerusalem")).toBe("יום שבת");
    expect(weekdayText(late, "UTC")).toBe("יום שישי");
  });
});
