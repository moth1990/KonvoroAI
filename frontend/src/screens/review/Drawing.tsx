import { useEffect, useRef } from "react";

import type { Quote } from "../../api/client";
import { Icon } from "../../ui/Icon";
import { ROUTES } from "../newQuote/model";
import {
  confidenceText,
  geometryText,
  kindLabel,
  overlays,
  pageNote,
  pageTitle,
  pageWarnings,
  panelFrames,
  routeLabel,
  stepPage,
  stripCount,
  stripLabel,
  stripTag,
  type Page,
} from "./drawingModel";
import type { Filter } from "./model";
import { Viewer, type FocusRequest, type ViewerHandle } from "./Viewer";

/**
 * The drawing pane (09 §6.5, prototype `vReview` drawing-pane and `setupViewer`): the page strip, the page in the
 * viewer with its boxes, the page's chips and the zoom tools. The layout and classes are the prototype's; the
 * spec's extras sit in its style (S11 decision 4): "עמוד x מתוך y" with previous / next, each thumbnail's count and
 * tag, and the classification row, read-only until S23.
 */
export function DrawingPane(props: {
  quote: Quote;
  pageId: string | null;
  onPage: (pageId: string) => void;
  selected: string | null;
  filter: Filter;
  activePanelId: string | null;
  focus: FocusRequest | null;
  finding: { pageId: string; bbox: number[] } | null;
  onSelectLine: (lineId: string) => void;
  onSelectPanel: (panelId: string) => void;
}) {
  const { quote } = props;
  const pages = quote.pages;
  const page = pages.find((p) => p.page_id === props.pageId) ?? pages[0];
  const viewer = useRef<ViewerHandle>(null);

  if (!page)
    return (
      <div className="drawing-soon">
        <b>אין שרטוט להצעה הזו</b>
      </div>
    );

  const boxes = overlays(quote, page, {
    selected: props.selected,
    filter: props.filter,
    activePanelId: props.activePanelId,
  });
  const note = pageNote(page);
  const warnings = pageWarnings(page);
  const conf = confidenceText(page);
  const geometry = geometryText(page);
  const go = (dir: 1 | -1) => {
    const next = stepPage(pages, page.page_id, dir);
    if (next) props.onPage(next);
  };
  const index = pages.indexOf(page);

  return (
    <>
      <Strip pages={pages} current={page.page_id} onPage={props.onPage} />
      <div className="viewer" data-route={page.route ?? ""}>
        {page.has_viewer ? (
          <Viewer
            ref={viewer}
            page={page}
            overlays={boxes}
            frames={panelFrames(page, props.activePanelId)}
            findingBox={props.finding && props.finding.pageId === page.page_id ? props.finding.bbox : null}
            focus={props.focus}
            onSelectLine={props.onSelectLine}
            onSelectPanel={props.onSelectPanel}
          />
        ) : (
          <div className="drawing-soon" data-testid="viewer" data-state="none">
            <b>התמונה של העמוד עוד לא מוכנה</b>
          </div>
        )}
        <div className="pageinfo" data-testid="pageinfo">
          <span className="chip acc">{pageTitle(page, pages.length)}</span>
          {page.route ? <span className={`chip ${ROUTES[page.route]?.chip ?? ""}`}>{routeLabel(page)}</span> : null}
          {conf ? <span className="chip">{conf}</span> : null}
          {geometry ? <span className="chip">{geometry}</span> : null}
          {note ? (
            <span className="chip" style={{ whiteSpace: "normal" }}>
              {note}
            </span>
          ) : null}
          {warnings.map((w) => (
            <span key={w} className="chip warn" role="note" style={{ whiteSpace: "normal" }}>
              {w}
            </span>
          ))}
        </div>
        <div className="vtools" role="toolbar" aria-label="כלי השרטוט">
          <button
            type="button"
            className="btn ghost sm"
            aria-label="העמוד הקודם"
            disabled={index <= 0}
            onClick={() => go(-1)}
          >
            <Icon name="back" />
          </button>
          <button
            type="button"
            className="btn ghost sm"
            aria-label="העמוד הבא"
            disabled={index >= pages.length - 1}
            onClick={() => go(1)}
          >
            <Icon name="fwd" />
          </button>
          <span className="vsep" aria-hidden="true" />
          <button type="button" className="btn ghost sm" aria-label="הגדל" onClick={() => viewer.current?.zoomIn()}>
            <Icon name="zin" />
          </button>
          <button type="button" className="btn ghost sm" aria-label="הקטן" onClick={() => viewer.current?.zoomOut()}>
            <Icon name="zout" />
          </button>
          <button type="button" className="btn ghost sm" aria-label="התאם לחלון" onClick={() => viewer.current?.fit()}>
            <Icon name="fit" />
          </button>
        </div>
      </div>
    </>
  );
}

/** 09 §6.5 "שורת עמודים": lazy thumbnails, the current page framed and scrolled into view. */
function Strip({ pages, current, onPage }: { pages: Page[]; current: string; onPage: (pageId: string) => void }) {
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = strip.current;
    if (!el) return;
    const show = () =>
      el
        .querySelector<HTMLElement>(`[data-page-id="${current}"]`)
        ?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    show();
    // On the phone the strip is in the drawing tab: scroll again when the tab opens and the strip gets a size.
    if (typeof ResizeObserver === "undefined") return;
    let shown = el.clientWidth > 0;
    const observer = new ResizeObserver(() => {
      if (!shown && el.clientWidth > 0) show();
      shown = el.clientWidth > 0;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [current]);
  return (
    <div className="strip" ref={strip} role="list" aria-label="עמודי השרטוט" data-testid="strip">
      {pages.map((p) => {
        const count = stripCount(p);
        const tag = stripTag(p);
        return (
          <div role="listitem" key={p.page_id}>
            <button
              type="button"
              className={`pg${p.route === "skip" ? " skip" : ""}`}
              data-page-id={p.page_id}
              data-testid="page-thumb"
              aria-current={p.page_id === current ? "true" : undefined}
              aria-label={stripLabel(p)}
              onClick={() => onPage(p.page_id)}
            >
              <span className="pg-img">
                {p.thumbnail_url ? <img src={p.thumbnail_url} alt="" loading="lazy" decoding="async" /> : null}
                {count ? <span className={`pg-count ${count.tone} num`}>{count.n}</span> : null}
              </span>
              <span>
                {p.page_no} · {kindLabel(p)}
              </span>
              {tag ? <span className="pg-tag">{tag}</span> : null}
            </button>
          </div>
        );
      })}
    </div>
  );
}
