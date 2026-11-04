import { describe, expect, it } from "vitest";

import type { Candidate } from "../../api/client";
import { originText, when } from "./model";

const TZ = "Asia/Jerusalem";
const NOW = new Date("2026-11-04T10:00:00Z");

describe("the queue card's source line", () => {
  it("says today, or the day and month, in the factory's time zone", () => {
    expect(when("2026-11-04T06:00:00Z", TZ, NOW)).toBe("היום");
    expect(when("2026-10-28T09:00:00Z", TZ, NOW)).toBe("28.10");
    expect(when("2026-11-03T22:30:00Z", TZ, NOW)).toBe("היום"); // already the 4th in Israel
    expect(when("2026-11-03T09:00:00Z", TZ, NOW)).toBe("03.11");
  });

  it("puts the origin before the date", () => {
    const c = { origin: "תיקון בהצעה", created_at: "2026-10-28T09:00:00Z" } as Candidate;
    expect(originText(c, TZ, NOW)).toBe("תיקון בהצעה, 28.10");
    expect(originText({ ...c, origin: "" }, TZ, NOW)).toBe("28.10");
  });
});
