/**
 * The drawing pane's logic, kept apart from OpenSeadragon so Vitest can test it (09 §6.5, §7.1; S11).
 *
 * Coordinates: boxes come in PDF points, origin top left (00 §6.2). OpenSeadragon's viewport measures the image in
 * widths (the image is 1 wide, `height / width` tall), so a point maps to the viewport by dividing by the page's
 * width in points. The page render keeps the page's aspect (stage 2 renders the upright page whole).
 */
import type { Finding, Quote, QuoteLine } from "../../api/client";
import { PAGE_KINDS, ROUTES } from "../newQuote/model";
import { matches, type Filter } from "./model";

export type Page = Quote["pages"][number];
export type Bbox = [number, number, number, number];

/** 01 §5.6: below this the classification is "not sure" (the same threshold as the confirmation step). */
export const UNSURE_BELOW = 0.85;

export interface ViewRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A bbox in points as a rectangle in the viewer's viewport (the image is 1 wide). */
export function toViewport(bbox: number[], widthPt: number): ViewRect {
  const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = bbox;
  return { x: x0 / widthPt, y: y0 / widthPt, width: (x1 - x0) / widthPt, height: (y1 - y0) / widthPt };
}

/**
 * Where to look at a box: centred, with the box a third of the view, as the prototype's `focusOn` does. Returns a
 * viewport rectangle the viewer fits, at least `minWidth` of the image wide, so a tiny box keeps its surroundings.
 */
export function focusRect(bbox: number[], widthPt: number, aspect: number, minWidth = 0.12): ViewRect {
  const r = toViewport(bbox, widthPt);
  let width = Math.max(r.width * 3, r.height * 3 * aspect, minWidth);
  let height = width / aspect;
  if (height < r.height * 3) {
    height = r.height * 3;
    width = height * aspect;
  }
  return { x: r.x + r.width / 2 - width / 2, y: r.y + r.height / 2 - height / 2, width, height };
}

/**
 * 09 §7.1: the page to show for a line. The current page if the line has an instance on it, otherwise the first page
 * that has one (in page order); null when the line has no instance (a manual or derived line).
 */
export function pageForLine(line: QuoteLine, currentPageId: string | null, pages: Page[]): string | null {
  if (!line.boxes.length) return null;
  if (currentPageId && line.boxes.some((b) => b.page_id === currentPageId)) return currentPageId;
  const order = new Map(pages.map((p, i) => [p.page_id, i]));
  const first = [...line.boxes].sort((a, b) => (order.get(a.page_id) ?? 1e9) - (order.get(b.page_id) ?? 1e9))[0];
  return first?.page_id ?? null;
}

/** The first box of the line on that page: what "show on drawing" frames. */
export function boxOnPage(line: QuoteLine, pageId: string): number[] | null {
  return line.boxes.find((b) => b.page_id === pageId)?.bbox ?? null;
}

export interface Overlay {
  key: string;
  lineId: string;
  bbox: number[];
  tone: "g" | "y" | "r";
  selected: boolean;
  dimmed: boolean;
  label: string;
}

/**
 * 09 §6.5: every instance on the page, in its line's status color. The selected line's instances are highlighted,
 * and a line hidden by the filter or in another panel than the active one is dimmed. Context and skipped pages show
 * the image only. The selected line's boxes are drawn last, so they sit on top.
 */
export function overlays(
  quote: Quote,
  page: Page,
  opts: { selected: string | null; filter: Filter; activePanelId: string | null },
): Overlay[] {
  if (page.route !== "process") return [];
  const out: Overlay[] = [];
  for (const panel of quote.panels) {
    const active = opts.activePanelId == null || panel.panel_id === opts.activePanelId;
    for (const line of panel.lines) {
      line.boxes.forEach((b, i) => {
        if (b.page_id !== page.page_id) return;
        out.push({
          key: `${line.line_id}:${i}`,
          lineId: line.line_id,
          bbox: b.bbox,
          tone: TONES[line.status],
          selected: line.line_id === opts.selected,
          dimmed: !active || !matches(line, opts.filter),
          label: overlayLabel(line),
        });
      });
    }
  }
  return out.sort((a, b) => Number(a.selected) - Number(b.selected));
}

const TONES = { green: "g", yellow: "y", red: "r" } as const;

/** The hover title: the line's name and its tags (09 §6.5 "ריחוף"). */
export function overlayLabel(line: QuoteLine): string {
  return line.designators.length ? `${line.description} · ${line.designators.join(", ")}` : line.description;
}

export interface PanelFrame {
  panelId: string;
  name: string;
  bbox: number[];
  active: boolean;
}

/** 09 §6.5: a page with more than one panel frames each, the active one solid, the others veiled to switch to. */
export function panelFrames(page: Page, activePanelId: string | null): PanelFrame[] {
  const boxed = page.panels.filter((p): p is typeof p & { bbox: number[] } => !!p.bbox && p.bbox.length === 4);
  if (page.route !== "process" || page.panels.length < 2 || !boxed.length) return [];
  return boxed.map((p) => ({ panelId: p.panel_id, name: p.name, bbox: p.bbox, active: p.panel_id === activePanelId }));
}

export function kindLabel(page: Page): string {
  return page.page_kind ? (PAGE_KINDS[page.page_kind] ?? page.page_kind) : "לא סווג";
}

export function routeLabel(page: Page): string {
  return page.route ? (ROUTES[page.route]?.label ?? page.route) : "";
}

/** "עמוד 5 מתוך 9 · E-104 · חד-קווי" (09 §6.5, page navigation). */
export function pageTitle(page: Page, total: number): string {
  return [`עמוד ${page.page_no} מתוך ${total}`, page.sheet, kindLabel(page)].filter(Boolean).join(" · ");
}

/** The strip's counter: red lines on the page, or if none, yellow ones (09 §6.5). */
export function stripCount(page: Page): { tone: "r" | "y"; n: number } | null {
  if (page.red_count) return { tone: "r", n: page.red_count };
  if (page.yellow_count) return { tone: "y", n: page.yellow_count };
  return null;
}

export function unsure(page: Page): boolean {
  return page.classified_by !== "user" && page.page_kind_confidence != null && page.page_kind_confidence < UNSURE_BELOW;
}

export function lowQuality(page: Page): boolean {
  return page.quality === "low_resolution";
}

/** The strip's tag (09 §6.5): low quality first, then an uncertain classification. */
export function stripTag(page: Page): string | null {
  if (lowQuality(page)) return "איכות נמוכה";
  if (unsure(page)) return "סיווג לא ודאי";
  return null;
}

/** A thumbnail's accessible name: number, content and tag (09 §13). */
export function stripLabel(page: Page): string {
  const count = stripCount(page);
  const parts = [`עמוד ${page.page_no}`, kindLabel(page), routeLabel(page)];
  if (count) parts.push(count.tone === "r" ? `${count.n} לא זוהו או שגויות` : `${count.n} לבדיקה`);
  const tag = stripTag(page);
  if (tag) parts.push(tag);
  return parts.filter(Boolean).join(", ");
}

/** The classification row, read-only until S23 (S11 decision 4): confidence, or "נקבע ידנית". */
export function confidenceText(page: Page): string | null {
  if (page.classified_by === "user") return "נקבע ידנית";
  if (page.page_kind_confidence == null) return null;
  return `ביטחון ${Math.round(page.page_kind_confidence * 100)}%`;
}

export function geometryText(page: Page): string | null {
  if (page.geometry_source === "vector") return "וקטורי";
  if (page.geometry_source === "raster") return "סרוק";
  return null;
}

/**
 * The page's warnings (09 §6.5). Changing the kind and uploading the original arrive with S23 (09 §7.9–7.10), so the
 * text says what is wrong without pointing at a control the screen doesn't have yet.
 */
export function pageWarnings(page: Page): string[] {
  const out: string[] = [];
  if (unsure(page)) out.push("הסיווג של העמוד לא ודאי");
  if (lowQuality(page)) out.push("העמוד סרוק ברזולוציה נמוכה, והטקסט נקרא ב-OCR. ייתכנו טעויות בקריאה");
  return out;
}

/** What a page that is not decoded is for (09 §6.5 "עמוד הקשר": the image, and its role below). */
export function pageNote(page: Page): string | null {
  if (page.route === "process") return null;
  if (page.route === "skip")
    return page.page_kind === "factory_template"
      ? "זוהה כתבנית קבועה של המפעל. לא נשלח לפענוח"
      : "העמוד דולג ולא נשלח לפענוח";
  return CONTEXT_NOTES[page.page_kind ?? ""] ?? "עמוד הקשר: נקרא לפרטים כלליים, ורכיבים לא נספרים ממנו";
}

const CONTEXT_NOTES: Record<string, string> = {
  technical_data: "מידות הארון, IP, זרם הלוח ומתח הפיקוד נקראים מכאן",
  panel_front_view: "משמש לבדיקה צולבת של התגים. רכיבים לא נספרים מכאן",
  legend: "המקרא משמש לזיהוי הסמלים בשרטוט",
  general_notes: "ההערות נקראות כהקשר להצעה",
  bom_table: "כתב הכמויות משמש לבדיקה צולבת של הכמויות",
  title_cover: "עמוד השער נקרא לפרטי הפרויקט",
};

/** A finding's box, for "בשרטוט" (prototype `f-show`). */
export function findingBox(f: Finding): { pageId: string; bbox: number[] } | null {
  return f.page_id && f.bbox && f.bbox.length === 4 ? { pageId: f.page_id, bbox: f.bbox } : null;
}

/** PgDn / PgUp (09 §8) and the toolbar's next / previous: clamped, no wrap. */
export function stepPage(pages: Page[], current: string | null, dir: 1 | -1): string | null {
  if (!pages.length) return null;
  const i = pages.findIndex((p) => p.page_id === current);
  if (i < 0) return pages[0]?.page_id ?? null;
  return pages[Math.min(pages.length - 1, Math.max(0, i + dir))]?.page_id ?? null;
}

/** The page the drawing opens on: the first decoded page, or the first page (prototype `S.page`). */
export function firstPage(pages: Page[]): string | null {
  return (pages.find((p) => p.route === "process") ?? pages[0])?.page_id ?? null;
}
