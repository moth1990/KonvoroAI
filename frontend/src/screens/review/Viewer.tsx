import OpenSeadragon from "openseadragon";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { API_BASE } from "../../api/client";
import { getToken } from "../../api/token";
import { focusRect, toViewport, type Overlay, type Page, type PanelFrame } from "./drawingModel";

// OpenSeadragon logs whole objects in its warnings ("Ignoring tile %s"), a tile's ajax headers included, and so the
// bearer token: in the browser's console, and in `make dev`'s terminal, which Vite forwards it to. Keep the text only.
function textOnly(log: (...args: unknown[]) => void) {
  return (...args: unknown[]) => log(...args.filter((a) => a == null || typeof a !== "object"));
}
(
  OpenSeadragon as unknown as { console: Pick<Console, "log" | "debug" | "info" | "warn" | "error" | "assert"> }
).console = {
  log: textOnly(console.log),
  debug: textOnly(console.debug),
  info: textOnly(console.info),
  warn: textOnly(console.warn),
  error: textOnly(console.error),
  assert: (cond?: boolean, ...args: unknown[]) => console.assert(cond, ...args.filter((a) => typeof a !== "object")),
};

/** The toolbar's zoom buttons step ×1.5 (S11 decision 4). */
export const ZOOM_STEP = 1.5;

export interface ViewerHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fit: () => void;
}

/** A request to frame a box ("הצג בשרטוט", a finding's "בשרטוט"), or to centre on it when zoomed in (09 §7.1). */
export interface FocusRequest {
  pageId: string;
  bbox: number[];
  mode: "frame" | "center";
  nonce: number;
}

export interface ViewerProps {
  page: Page;
  overlays: Overlay[];
  frames: PanelFrame[];
  findingBox: number[] | null;
  focus: FocusRequest | null;
  onSelectLine: (lineId: string) => void;
  onSelectPanel: (panelId: string) => void;
}

function reducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The page in OpenSeadragon (BSD, 12 §6), tile by tile from the API's pyramid with the bearer token on every
 * request, and an SVG layer of boxes in PDF points on top (09 §6.5). The SVG is an OpenSeadragon overlay over the
 * whole image, so it pans and zooms with it, and a drag that starts on a box still pans. A click (not a drag) on a
 * box selects its line; on a veiled panel, switches to that panel.
 */
export const Viewer = forwardRef<ViewerHandle, ViewerProps>(function Viewer(props, ref) {
  const host = useRef<HTMLDivElement>(null);
  const osd = useRef<OpenSeadragon.Viewer | null>(null);
  const [layer] = useState(() => document.createElement("div"));
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [ready, setReady] = useState(false);
  const callbacks = useRef(props);
  const pendingFocus = useRef<FocusRequest | null>(null);
  const lastFocus = useRef<FocusRequest | null>(null); // applied, for a viewer that was hidden and appears
  const openPage = useRef<string | null>(null); // the page whose pyramid is open, once its "open" fired
  useEffect(() => {
    callbacks.current = props;
  });

  // One OpenSeadragon per mount; pages open into it.
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const still = reducedMotion();
    const viewer = OpenSeadragon({
      element,
      showNavigationControl: false,
      loadTilesWithAjax: true,
      ajaxHeaders: { Authorization: `Bearer ${getToken() ?? ""}` },
      animationTime: still ? 0 : 0.4,
      springStiffness: still ? 100 : 6.5,
      visibilityRatio: 0.5,
      // The prototype fits the page at 96% (`setupViewer`); here, room for the page chips above and the tools below.
      viewportMargins: { top: 44, bottom: 60, left: 16, right: 16 },
      minZoomImageRatio: 0.8,
      maxZoomPixelRatio: 3,
      gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: true },
      gestureSettingsTouch: { clickToZoom: false, dblClickToZoom: true },
      preserveImageSizeOnResize: false,
      drawer: "canvas",
      crossOriginPolicy: false,
    });
    viewer.addHandler("canvas-click", (e) => {
      if (!e.quick) return;
      // OpenSeadragon captures the pointer, so the event's target is its canvas: find the box under the point.
      const at = e.originalEvent as MouseEvent;
      const target = document
        .elementsFromPoint(at.clientX, at.clientY)
        .map((el) => el.closest("[data-line-id], [data-panel-id]"))
        .find(Boolean);
      const lineId = target?.getAttribute("data-line-id");
      const panelId = target?.getAttribute("data-panel-id");
      if (lineId) callbacks.current.onSelectLine(lineId);
      else if (panelId) callbacks.current.onSelectPanel(panelId);
    });
    viewer.addHandler("open", () => {
      const item = viewer.world.getItemAt(0);
      if (!item) return;
      const content = item.getContentSize();
      const page = callbacks.current.page;
      openPage.current = page.page_id;
      const w = page.width_pt ?? content.x;
      setSize({ w, h: (w * content.y) / content.x });
      viewer.addOverlay({ element: layer, location: new OpenSeadragon.Rect(0, 0, 1, content.y / content.x) });
      item.addHandler("fully-loaded-change", (ev) => setReady(ev.fullyLoaded));
      setReady(item.getFullyLoaded());
      const focus = pendingFocus.current;
      const container = viewer.viewport.getContainerSize();
      if (focus && focus.pageId === page.page_id && container.x && container.y) {
        pendingFocus.current = null;
        lastFocus.current = focus;
        apply(viewer, focus, w, true);
      }
    });
    osd.current = viewer;

    // On the phone the drawing is a tab: a viewer made or focused while hidden has no size. When it appears, fit
    // the page, or do the focus that was waiting for a size.
    let hidden = element.clientWidth === 0 || element.clientHeight === 0;
    let frame = 0;
    const sized = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(appeared); // after layout: resizing inside the callback loops the observer
    });
    function appeared() {
      if (!element) return;
      const now = element.clientWidth === 0 || element.clientHeight === 0;
      if (hidden && !now && viewer.world.getItemAt(0) && openPage.current) {
        viewer.forceResize();
        const focus = pendingFocus.current ?? lastFocus.current;
        const w = callbacks.current.page.width_pt;
        if (focus && focus.pageId === openPage.current && w) {
          pendingFocus.current = null;
          lastFocus.current = focus;
          apply(viewer, focus, w, true);
        } else viewer.viewport.goHome(true);
      }
      hidden = now;
    }
    sized.observe(element);
    return () => {
      cancelAnimationFrame(frame);
      sized.disconnect();
      viewer.destroy();
      osd.current = null;
    };
  }, [layer]);

  // Another page: open its pyramid. The token may have changed since the viewer was made.
  const pageId = props.page.page_id;
  const hasViewer = props.page.has_viewer;
  useEffect(() => {
    const viewer = osd.current;
    if (!viewer) return;
    setReady(false);
    setSize(null);
    openPage.current = null;
    lastFocus.current = null;
    if (!hasViewer) {
      viewer.close();
      return;
    }
    viewer.setAjaxHeaders({ Authorization: `Bearer ${getToken() ?? ""}` });
    viewer.open({ tileSource: `${API_BASE}/pages/${pageId}/dz/page.dzi` });
  }, [pageId, hasViewer]);

  // A focus request: now if its page is open, otherwise once it opens.
  const focus = props.focus;
  useEffect(() => {
    const viewer = osd.current;
    if (!viewer || !focus) return;
    const container = viewer.viewport.getContainerSize();
    if (openPage.current !== focus.pageId || focus.pageId !== pageId || !size || !container.x || !container.y) {
      pendingFocus.current = focus;
      return;
    }
    lastFocus.current = focus;
    apply(viewer, focus, size.w, false);
  }, [focus, pageId, size]);

  useImperativeHandle(
    ref,
    () => ({
      zoomIn: () => zoomBy(osd.current, ZOOM_STEP),
      zoomOut: () => zoomBy(osd.current, 1 / ZOOM_STEP),
      fit: () => osd.current?.viewport.goHome(),
    }),
    [],
  );

  return (
    <div
      className="osd"
      ref={host}
      dir="ltr"
      data-testid="viewer"
      data-page={pageId}
      data-state={hasViewer ? (ready ? "ready" : "loading") : "none"}
    >
      {size
        ? createPortal(
            <Boxes
              width={size.w}
              height={size.h}
              overlays={props.overlays}
              frames={props.frames}
              findingBox={props.findingBox}
            />,
            layer,
          )
        : null}
    </div>
  );
});

function zoomBy(viewer: OpenSeadragon.Viewer | null, factor: number): void {
  if (!viewer) return;
  viewer.viewport.zoomBy(factor);
  viewer.viewport.applyConstraints();
}

function apply(viewer: OpenSeadragon.Viewer, f: FocusRequest, widthPt: number, now: boolean): void {
  const vp = viewer.viewport;
  if (f.mode === "center") {
    // 09 §6.5: selecting a line centres its component only when the drawing is zoomed in.
    if (vp.getZoom() <= vp.getHomeZoom() * 1.05) return;
    const r = toViewport(f.bbox, widthPt);
    vp.panTo(new OpenSeadragon.Point(r.x + r.width / 2, r.y + r.height / 2), now);
    return;
  }
  const container = vp.getContainerSize();
  const r = focusRect(f.bbox, widthPt, container.x / Math.max(1, container.y));
  vp.fitBounds(new OpenSeadragon.Rect(r.x, r.y, r.width, r.height), now);
}

/**
 * The boxes, in PDF points (00 §6.2). Strokes keep their width at any zoom. Red is dashed, so the status reads
 * without color (09 §13); the selected line is thick in the accent color; dimmed boxes are faint.
 */
function Boxes(props: {
  width: number;
  height: number;
  overlays: Overlay[];
  frames: PanelFrame[];
  findingBox: number[] | null;
}) {
  return (
    <svg
      className="hl-layer"
      viewBox={`0 0 ${props.width} ${props.height}`}
      preserveAspectRatio="none"
      width="100%"
      height="100%"
      data-testid="hl-layer"
    >
      {props.frames.map((f) => {
        const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = f.bbox;
        return (
          <g key={f.panelId} className={`pframe${f.active ? " active" : ""}`} data-testid="panel-frame">
            {f.active ? null : (
              <rect
                className="veil"
                x={x0}
                y={y0}
                width={x1 - x0}
                height={y1 - y0}
                data-panel-id={f.panelId}
                role="button"
                aria-label={`מעבר ללוח ${f.name}`}
              >
                <title>לחצו למעבר</title>
              </rect>
            )}
            <rect className="frame" x={x0} y={y0} width={x1 - x0} height={y1 - y0} vectorEffect="non-scaling-stroke" />
            <text className="frame-name" x={x0 + 4} y={y0 - 4}>
              {f.name}
            </text>
            {f.active ? null : (
              <text className="veil-text" x={(x0 + x1) / 2} y={(y0 + y1) / 2} textAnchor="middle">
                לחצו למעבר
              </text>
            )}
          </g>
        );
      })}
      {props.overlays.map((o) => {
        const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = o.bbox;
        return (
          <rect
            key={o.key}
            className={`hl ${o.tone}${o.selected ? " sel" : ""}${o.dimmed ? " dim" : ""}`}
            x={x0}
            y={y0}
            width={x1 - x0}
            height={y1 - y0}
            rx={2}
            vectorEffect="non-scaling-stroke"
            data-line-id={o.lineId}
            data-testid="hl"
            data-selected={o.selected || undefined}
          >
            <title>{o.label}</title>
          </rect>
        );
      })}
      {props.findingBox ? (
        <rect
          className="hl find"
          x={props.findingBox[0]}
          y={props.findingBox[1]}
          width={(props.findingBox[2] ?? 0) - (props.findingBox[0] ?? 0)}
          height={(props.findingBox[3] ?? 0) - (props.findingBox[1] ?? 0)}
          rx={2}
          vectorEffect="non-scaling-stroke"
          data-testid="hl-finding"
        />
      ) : null}
    </svg>
  );
}
