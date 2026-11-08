import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Live, Progress } from "../../api/client";
import { endWatch, resetWatch, setNotify, watchedRun, watchRun } from "../../shell/runWatch";
import {
  aboutMin,
  announceHidden,
  boxStyle,
  counterItems,
  estimateText,
  finishedText,
  isolate,
  leftText,
  liveSentence,
  mmss,
  modelsText,
  readyTitle,
  shownEstimate,
  stagesTitle,
  stepText,
  usd,
} from "./live";
import type { PickedFile } from "./model";

const LIVE: Live = {
  started_at: "2026-11-08T10:00:00Z",
  elapsed_s: 30,
  seconds_left: 150,
  seconds_expected: 167,
  fraction: 0.2,
  cost_usd: "0.104",
  cost_estimate_usd: "0.4421",
  cost_per_page_usd: null,
  stages: [],
  messages: [
    { stage: 1, text: "עמוד 1: נתונים טכניים", at_s: 2 },
    { stage: 3, text: "עמוד 5: 18 רכיבים", at_s: 28 },
  ],
  counters: { pages: 9, pages_read: 9, tiles: 58, components: 18 },
  view: null,
};

function progress(over: Partial<Progress> = {}): Progress {
  return {
    drawing_id: "drw_1",
    name: "גן ילדים",
    status: "processing",
    current_stage: 3,
    progress: 0.3,
    counted_as: "new_drawing",
    counted: false,
    files: [{ name: "NURSERY-1.pdf", page_count: 9 }],
    stages: [
      { stage: 1, name: "קליטת השרטוט", status: "done" },
      { stage: 2, name: "קריאת הטקסט", status: "done" },
      { stage: 3, name: "זיהוי הרכיבים", status: "running" },
      { stage: 4, name: "חיבור תוויות לרכיבים", status: "queued" },
    ],
    quote_id: null,
    pages: [],
    confirmation_reasons: [],
    notices: [],
    live: LIVE,
    ...over,
  } as Progress;
}

describe("the live run's numbers", () => {
  it("formats dollars to the cent from the API's string", () => {
    expect(usd("0.104")).toBe("$0.10");
    expect(usd("0.4451")).toBe("$0.45");
    expect(usd(null)).toBe("$0.00");
    expect(usd("nonsense")).toBe("$0.00");
  });

  it("writes time as minutes and seconds", () => {
    expect(mmss(0)).toBe("0:00");
    expect(mmss(152.7)).toBe("2:32");
    expect(mmss(-3)).toBe("0:00");
  });

  it("says the start bar's time in words", () => {
    expect(aboutMin(40)).toBe("פחות מדקה");
    expect(aboutMin(70)).toBe("כדקה");
    expect(aboutMin(152)).toBe("כ-3 דקות");
  });

  it("says the time left as one rounded number, a few seconds near the end", () => {
    expect(leftText(LIVE)).toBe("נותרו כ-2:30");
    expect(leftText({ ...LIVE, seconds_left: 10 })).toBe("נותרו כמה שניות");
    expect(leftText({ ...LIVE, elapsed_s: 1 })).toBe("צפוי כ-2:50"); // before anything ran: the whole run
    expect(leftText({ ...LIVE, seconds_left: null })).toBe("");
  });

  it("writes the start bar's estimate", () => {
    expect(estimateText({ pages: 9, seconds: 152, cost_usd: "0.44" })).toBe("9 עמודים · כ-3 דקות · כ-$0.44");
    expect(estimateText({ pages: 1, seconds: 17, cost_usd: "0.05" })).toBe("עמוד אחד · פחות מדקה · כ-$0.05");
  });
});

describe("the start bar's estimate", () => {
  const file = (over: Partial<PickedFile>): PickedFile => ({ key: "k", file: new File([""], "a.pdf"), ...over });
  const estimate = { pages: 9, seconds: 152, cost_usd: "0.44" };

  it("shows only when every file's pages are known and none is rejected", () => {
    expect(shownEstimate([file({ pages: 9 })], estimate)).toBe(estimate);
    expect(shownEstimate([file({ pages: 9 }), file({ pages: null })], estimate)).toBeNull();
    expect(shownEstimate([file({ pages: 9, error: { code: "too_large", message: "x" } })], estimate)).toBeNull();
    expect(shownEstimate([], estimate)).toBeNull();
    expect(shownEstimate([file({ pages: 9 })], null)).toBeNull();
  });
});

describe("the live run's words", () => {
  it("names the running stage and its latest sentence", () => {
    expect(liveSentence(progress())).toBe("זיהוי הרכיבים: עמוד 5: 18 רכיבים");
    expect(stepText(progress())).toBe("שלב 3 מתוך 4");
  });

  it("names the next stage while the drawing waits in the queue, and ends with מסיים", () => {
    const waiting = progress({
      stages: [
        { stage: 1, name: "קליטת השרטוט", status: "done" },
        { stage: 2, name: "קריאת הטקסט", status: "queued" },
      ],
    });
    expect(liveSentence(waiting)).toBe("קריאת הטקסט");
    expect(stepText(progress({ stages: [{ stage: 1, name: "קליטת השרטוט", status: "done" }] }))).toBe("מסיים");
  });

  it("counts the upload's pages before stage 1 reports", () => {
    expect(counterItems({}, 9)[0]).toEqual({ label: "עמודים", value: "0/9" });
  });

  it("counts pages read out of all, and the rest as they come", () => {
    expect(counterItems(LIVE.counters)).toEqual([
      { label: "עמודים", value: "9/9" },
      { label: "אריחים", value: "58" },
      { label: "רכיבים", value: "18" },
      { label: "מוצרים", value: "0" },
      { label: "ממצאים", value: "0" },
    ]);
  });

  it("says what ran in a stage, or that it is code only", () => {
    expect(modelsText([{ label: "Haiku", calls: 4 }], 1)).toBe("Haiku × 4");
    expect(modelsText([], 7)).toBe("קוד בלבד");
    expect(modelsText([], 5)).toBe("בלי מודל");
    expect(stagesTitle(7)).toBe("שבעה שלבים");
    expect(stagesTitle(5)).toBe("חמישה שלבים");
  });

  it("places a box in points from the inline start, the page not mirrored", () => {
    expect(boxStyle([100, 50, 200, 150], [1000, 500])).toEqual({
      insetInlineStart: "80.00%",
      top: "10.00%",
      width: "10.00%",
      height: "20.00%",
    });
  });

  it("tells about the end on another screen", () => {
    const ready = progress({
      status: "ready",
      summary: {
        input_kind: "factory_drawing",
        panels: [],
        page_count: 9,
        pages_by_route: {},
        products: 13,
        priced: 8,
        findings: 4,
      },
    });
    expect(finishedText("quote", ready)).toBe("הפענוח של גן ילדים הסתיים: 13 מוצרים. לבדיקה ← הצעה חדשה");
    expect(finishedText("quote", progress({ status: "failed" }))).toBe("הפענוח של גן ילדים נכשל. הפרטים ← הצעה חדשה");
    expect(finishedText("audit", progress({ status: "ready" }))).toBe(
      "הבדיקה של גן ילדים הסתיימה. התוצאות ← בדיקת הצעה",
    );
    expect(isolate("$0.12")).toBe("⁦$0.12⁩");
  });
});

describe("a hidden tab at the end", () => {
  let hidden = false;
  beforeEach(() => {
    hidden = false;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    document.title = "קונבורו";
  });
  afterEach(() => vi.restoreAllMocks());

  it("says ✓ מוכן in the title until the user comes back", () => {
    expect(announceHidden("הסתיים", false)).toBe(false); // a visible tab: the toast is enough
    expect(document.title).toBe("קונבורו");
    hidden = true;
    expect(announceHidden("הסתיים", false)).toBe(true);
    expect(document.title).toBe("✓ מוכן · קונבורו");
    document.dispatchEvent(new Event("visibilitychange"));
    expect(document.title).toBe("קונבורו");
    expect(readyTitle("✓ מוכן · קונבורו")).toBe("✓ מוכן · קונבורו");
  });

  it("sends a notification only when the user asked and the browser allows", () => {
    const sent: string[] = [];
    class FakeNotification {
      static permission = "granted";
      constructor(_title: string, options: { body: string }) {
        sent.push(options.body);
      }
      close() {}
    }
    vi.stubGlobal("Notification", FakeNotification);
    hidden = true;
    announceHidden("הסתיים", false);
    announceHidden("הסתיים", true);
    FakeNotification.permission = "denied";
    announceHidden("שוב", true);
    expect(sent).toEqual(["הסתיים"]);
    vi.unstubAllGlobals();
  });
});

describe("the watched run", () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetWatch();
  });

  it("keeps one run, its notify choice, and forgets it at the end", () => {
    watchRun({ drawingId: "drw_1", name: "גן", kind: "quote" });
    setNotify("drw_1", true);
    setNotify("drw_other", false); // another run's switch changes nothing
    resetWatch(); // a reload reads it back
    expect(watchedRun()).toEqual({ drawingId: "drw_1", name: "גן", kind: "quote", notify: true });
    watchRun({ drawingId: "drw_1", name: "גן", kind: "quote" }); // the same run again keeps the choice
    expect(watchedRun()?.notify).toBe(true);
    endWatch("drw_other");
    expect(watchedRun()?.drawingId).toBe("drw_1");
    endWatch("drw_1");
    expect(watchedRun()).toBeNull();
  });

  it("works without storage", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    watchRun({ drawingId: "drw_2", name: "x", kind: "audit" });
    expect(watchedRun()?.drawingId).toBe("drw_2");
    vi.restoreAllMocks();
  });
});
