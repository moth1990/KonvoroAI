import { describe, expect, it } from "vitest";

import {
  confidenceText,
  findingBox,
  firstPage,
  focusRect,
  overlays,
  pageForLine,
  pageNote,
  pageTitle,
  pageWarnings,
  panelFrames,
  stepPage,
  stripCount,
  stripLabel,
  stripTag,
  toViewport,
} from "./drawingModel";
import { finding, line, page, panel, quote } from "./fixtures";

const p4 = page(4, { route: "context", page_kind: "panel_front_view" });
const p5 = page(5, { sheet: "E-104" });
const p8 = page(8);
const pages = [p4, p5, p8];
const at = (p: typeof p5, bbox: number[]) => ({ page_id: p.page_id, bbox });

describe("coordinates (00 §6.2)", () => {
  it("maps PDF points to the viewer's viewport, which is 1 wide", () => {
    const r = toViewport([84.2, 59.5, 168.4, 119], 842);
    expect([r.x, r.y, r.width, r.height].map((v) => +v.toFixed(4))).toEqual([0.1, 0.0707, 0.1, 0.0707]);
  });

  it("frames a box at a third of the view, centred on it", () => {
    const r = focusRect([421, 297.5, 463.1, 307.5], 842, 2, 0);
    expect(r.width).toBeCloseTo(0.15);
    expect(r.height).toBeCloseTo(0.075);
    expect(r.x + r.width / 2).toBeCloseTo(0.525);
    expect(r.y + r.height / 2).toBeCloseTo(0.3593);
  });

  it("keeps a tall box whole and a tiny one in its surroundings", () => {
    const tall = focusRect([0, 0, 8.42, 168.4], 842, 2, 0);
    expect(tall.height).toBeCloseTo(0.6);
    expect(tall.width).toBeCloseTo(1.2);
    expect(focusRect([0, 0, 1, 1], 842, 2).width).toBe(0.12);
  });
});

describe("the page for a line (09 §7.1)", () => {
  const rnv = line({ boxes: [at(p8, [1, 2, 3, 4]), at(p5, [5, 6, 7, 8])] });

  it("stays on the current page when the line is on it", () => {
    expect(pageForLine(rnv, p8.page_id, pages)).toBe(p8.page_id);
  });

  it("otherwise goes to the first page, in page order, not box order", () => {
    expect(pageForLine(rnv, p4.page_id, pages)).toBe(p5.page_id);
    expect(pageForLine(rnv, null, pages)).toBe(p5.page_id);
  });

  it("a line with no instance has no page", () => {
    expect(pageForLine(line(), p5.page_id, pages)).toBeNull();
  });
});

describe("boxes on the page (09 §6.5, S11 decision 1)", () => {
  const f1 = line({ status: "green", boxes: [at(p5, [10, 10, 20, 20]), at(p5, [30, 10, 40, 20])] });
  const q0 = line({ status: "red", designators: ["Q0"], description: "מפסק ראשי", boxes: [at(p5, [50, 50, 90, 90])] });
  const c1 = line({ status: "yellow", boxes: [at(p8, [1, 1, 2, 2])] });
  const other = line({ status: "yellow", boxes: [at(p5, [100, 100, 110, 110])] });
  const q = quote([panel("A", [f1, q0, c1]), panel("B", [other])]);

  it("every instance on the page, in its line's color", () => {
    const out = overlays(q, p5, { selected: null, filter: "all", activePanelId: "pnl_A" });
    expect(out.map((o) => [o.lineId, o.tone])).toEqual([
      [f1.line_id, "g"],
      [f1.line_id, "g"],
      [q0.line_id, "r"],
      [other.line_id, "y"],
    ]);
    expect(out[2]?.label).toBe("מפסק ראשי · Q0");
  });

  it("the selected line's boxes are marked and drawn last, on top", () => {
    const out = overlays(q, p5, { selected: f1.line_id, filter: "all", activePanelId: "pnl_A" });
    expect(out.slice(-2).every((o) => o.selected && o.lineId === f1.line_id)).toBe(true);
    expect(out.filter((o) => o.selected)).toHaveLength(2);
  });

  it("dims what the filter hides and what belongs to another panel", () => {
    const out = overlays(q, p5, { selected: null, filter: "red", activePanelId: "pnl_A" });
    const dim = Object.fromEntries(out.map((o) => [o.lineId, o.dimmed]));
    expect(dim).toEqual({ [f1.line_id]: true, [q0.line_id]: false, [other.line_id]: true });
  });

  it("a context or skipped page shows the image only", () => {
    expect(overlays(q, { ...p5, route: "context" }, { selected: null, filter: "all", activePanelId: null })).toEqual(
      [],
    );
  });
});

describe("panel frames (09 §6.5)", () => {
  const two = page(6, {
    panels: [
      { panel_id: "pnl_A", name: "לוח 1", bbox: [0, 0, 400, 595] },
      { panel_id: "pnl_B", name: "לוח 2", bbox: [420, 0, 842, 595] },
    ],
  });

  it("frames each panel on a page with more than one, the active one solid", () => {
    expect(panelFrames(two, "pnl_B").map((f) => [f.name, f.active])).toEqual([
      ["לוח 1", false],
      ["לוח 2", true],
    ]);
  });

  it("no frames for one panel, or panels the classifier didn't box", () => {
    expect(panelFrames(page(6, { panels: [{ panel_id: "pnl_A", name: "א", bbox: [0, 0, 1, 1] }] }), "pnl_A")).toEqual(
      [],
    );
    const unboxed = page(6, {
      panels: [
        { panel_id: "pnl_A", name: "א", bbox: null },
        { panel_id: "pnl_B", name: "ב", bbox: null },
      ],
    });
    expect(panelFrames(unboxed, "pnl_A")).toEqual([]);
  });
});

describe("the strip and the page chips (09 §6.5, S11 decision 4)", () => {
  it("names the page: number of total, sheet, kind", () => {
    expect(pageTitle(p5, 9)).toBe("עמוד 5 מתוך 9 · E-104 · חד-קווי");
    expect(pageTitle(p4, 9)).toBe("עמוד 4 מתוך 9 · חזית לוח");
  });

  it("counts red lines, or if none, yellow ones", () => {
    expect(stripCount(page(1, { red_count: 2, yellow_count: 3 }))).toEqual({ tone: "r", n: 2 });
    expect(stripCount(page(1, { yellow_count: 3 }))).toEqual({ tone: "y", n: 3 });
    expect(stripCount(page(1))).toBeNull();
  });

  it("tags low quality before an uncertain classification, and trusts the user's", () => {
    expect(stripTag(page(1, { quality: "low_resolution", page_kind_confidence: 0.4 }))).toBe("איכות נמוכה");
    expect(stripTag(page(1, { page_kind_confidence: 0.84 }))).toBe("סיווג לא ודאי");
    expect(stripTag(page(1, { page_kind_confidence: 0.85 }))).toBeNull();
    expect(stripTag(page(1, { page_kind_confidence: 0.4, classified_by: "user" }))).toBeNull();
  });

  it("a thumbnail's name has its number, content, route, count and tag (09 §13)", () => {
    expect(stripLabel(page(8, { red_count: 2, page_kind_confidence: 0.6 }))).toBe(
      "עמוד 8, חד-קווי, פענוח, 2 לא זוהו או שגויות, סיווג לא ודאי",
    );
    expect(stripLabel(p4)).toBe("עמוד 4, חזית לוח, הקשר");
  });

  it("the classification row: confidence or set by hand, and the warnings", () => {
    expect(confidenceText(p5)).toBe("ביטחון 95%");
    expect(confidenceText(page(1, { classified_by: "user" }))).toBe("נקבע ידנית");
    expect(pageWarnings(page(1, { page_kind_confidence: 0.6, quality: "low_resolution" }))).toHaveLength(2);
    expect(pageWarnings(p5)).toEqual([]);
  });

  it("explains a page that is not decoded", () => {
    expect(pageNote(p5)).toBeNull();
    expect(pageNote(p4)).toBe("משמש לבדיקה צולבת של התגים. רכיבים לא נספרים מכאן");
    expect(pageNote(page(2, { route: "skip", page_kind: "factory_template" }))).toBe(
      "זוהה כתבנית קבועה של המפעל. לא נשלח לפענוח",
    );
    expect(pageNote(page(3, { route: "context", page_kind: "other" }))).toMatch(/^עמוד הקשר/);
  });
});

describe("paging (09 §8)", () => {
  it("steps without wrapping", () => {
    expect(stepPage(pages, p5.page_id, 1)).toBe(p8.page_id);
    expect(stepPage(pages, p8.page_id, 1)).toBe(p8.page_id);
    expect(stepPage(pages, p4.page_id, -1)).toBe(p4.page_id);
    expect(stepPage([], null, 1)).toBeNull();
  });

  it("opens on the first decoded page", () => {
    expect(firstPage(pages)).toBe(p5.page_id);
    expect(firstPage([p4])).toBe(p4.page_id);
    expect(firstPage([])).toBeNull();
  });

  it("a finding without a box has nothing to show", () => {
    expect(findingBox(finding())).toBeNull();
    expect(findingBox(finding({ page_id: p5.page_id, bbox: [1, 2, 3, 4] }))).toEqual({
      pageId: p5.page_id,
      bbox: [1, 2, 3, 4],
    });
  });
});
