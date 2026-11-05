import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  Fragment,
  type ReactNode,
} from "react";
import { Link, useParams } from "react-router";

import {
  ApiError,
  dismissFinding,
  fetchQuote,
  fetchUnresolved,
  lineAction,
  markComponent,
  openNextVersion,
  previewRecalculation,
  recalculateQuote,
  restoreLines,
  sendQuote,
  undoAction,
  type ActionResult,
  type DismissReason,
  type Finding,
  type LineAction,
  type ProductChoice,
  type ChatInstance,
  type Quote,
  type QuoteLine,
  type Recalculation,
} from "../../api/client";
import { useMe } from "../../api/QueryProvider";
import { Shell } from "../../shell/Shell";
import { MOBILE_MAX_PX } from "../../theme/tokens";
import { Icon } from "../../ui/Icon";
import { Modal } from "../../ui/Modal";
import { useToast } from "../../ui/Toast";
import { INPUT_KINDS } from "../newQuote/model";
import { ChatPanel, type ChatFocus } from "./Chat";
import { DrawingPane } from "./Drawing";
import { ExportModal } from "./ExportModal";
import { boxOnPage, canMark, findingBox, firstPage, overlays, pageForLine, stepPage, tooSmall } from "./drawingModel";
import { DismissControl, LineDetail, type DetailActions } from "./LineDetail";
import { ProductPicker } from "./ProductPicker";
import {
  belowFloor,
  buildRows,
  compactDesignators,
  FILTERS,
  filterCounts,
  nextFilter,
  panelTabs,
  percent,
  progress,
  qtyText,
  qtyTimesPrice,
  reasonChips,
  shekels,
  statusMark,
  stepLine,
  type Filter,
  type Row,
  type Shape,
  matches,
  nextToCheck,
  nextUnpriced,
  parseAmount,
  priceChips,
  sendSummary,
  takesPrice,
} from "./model";
import { isUndoKey, undoStackFor, useUndo } from "./undo";
import type { FocusRequest } from "./Viewer";

type Tab = "lines" | "drawing" | "chat";
const MARGIN_KEY = "konboro:review:margin"; // 09 §6.3: the margin column is remembered per user (this browser)
const PHONE = `(max-width: ${MOBILE_MAX_PX}px)`;

function usePhone(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(PHONE);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(PHONE).matches,
  );
}

function readMarginPref(): boolean {
  try {
    return window.localStorage.getItem(MARGIN_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * The review screen (09 §5–6.5, §8, prototype `vReview`): header, filters, findings, the grouped lines table and
 * line detail (S09), the drawing pane and undo (S11), the actions (S23, 09 §7), and the chat (S25, 08), a drawer over
 * the drawing on the desktop and the third tab on the phone, behind `chat_layer`.
 *
 * An action goes to the server and the screen shows what it answers: the server prices and colours every line
 * (09 principle 7), within 500 ms (09 §14), so the screen never guesses an amount it would have to take back.
 */
export function ReviewScreen() {
  const { quoteId = "" } = useParams();
  const quote = useQuery({ queryKey: ["quote", quoteId], queryFn: () => fetchQuote(quoteId), enabled: !!quoteId });
  let body;
  if (quote.data) body = <Review quote={quote.data} />;
  else if (quote.isError)
    body = (
      <div className="pad" style={{ display: "grid", gap: 12, justifyItems: "start" }}>
        <p className="err-msg" role="alert" style={{ margin: 0 }}>
          {quote.error instanceof ApiError && quote.error.status === 404
            ? "ההצעה לא נמצאה"
            : "לא הצלחנו לטעון את ההצעה. נסו לרענן את הדף"}
        </p>
        <Link className="btn sm" to="/home">
          חזרה לבית
        </Link>
      </div>
    );
  return <Shell bare>{body ?? null}</Shell>;
}

function Review({ quote }: { quote: Quote }) {
  const phone = usePhone();
  const [filter, setFilter] = useState<Filter>("all");
  const [panelIdx, setPanelIdx] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("lines");
  const [showMargin, setShowMargin] = useState(readMarginPref);
  const [pageId, setPageId] = useState<string | null>(() => firstPage(quote.pages));
  const [focus, setFocus] = useState<FocusRequest | null>(null);
  const [shownFinding, setShownFinding] = useState<{ pageId: string; bbox: number[] } | null>(null);
  const focusCount = useRef(0);
  const undo = useUndo(quote.quote_id);
  const toast = useToast();
  const me = useMe();
  const chatOn = !!me.data?.flags?.chat_layer;
  // 13 §4.4 (S26): the "לא פוענח" layer, on by default as in the prototype (`showUnresolved: true`), read again with
  // each answer the server gives (an action moves the revision)
  const unresolvedFlag = !!me.data?.flags?.unresolved_overlay;
  // 13 §4.1 (S26): "הורדה", the customer PDF and the internal Excel
  const exportOn = !!me.data?.flags?.export_doc;
  const [exporting, setExporting] = useState(false);
  const [showUnresolved, setShowUnresolved] = useState(true);
  const unresolved = useQuery({
    queryKey: ["unresolved", quote.quote_id, quote.version, quote.revision],
    queryFn: () => fetchUnresolved(quote.quote_id),
    enabled: unresolvedFlag,
    placeholderData: (previous) => previous,
  });
  const [chatOpen, setChatOpen] = useState(false);
  const chatInput = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const locked = quote.status === "sent";
  const [saveToList, setSaveToList] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [recalc, setRecalc] = useState<Recalculation | null>(null);
  const [dismissing, setDismissing] = useState<string | null>(null);
  // S23b: draw mode (09 §6.6) and the product picker, for a rectangle drawn or a missing line ("מוצר אחר…")
  const [drawing, setDrawing] = useState(false);
  const [picker, setPicker] = useState<
    { kind: "mark"; pageId: string; bbox: number[] } | { kind: "missing"; line: QuoteLine } | null
  >(null);

  const panel = quote.panels[Math.min(panelIdx, quote.panels.length - 1)];
  const allLines = useMemo(() => quote.panels.flatMap((p) => p.lines), [quote]);
  const rows = useMemo(() => (panel ? buildRows(panel, filter) : []), [panel, filter]);
  const lineIds = useMemo(() => rows.flatMap((r) => (r.kind === "line" ? [r.key] : [])), [rows]);
  const counts = filterCounts(panel?.lines ?? []);
  const prog = progress(allLines);
  const tabs = panelTabs(quote);
  const t = quote.totals;
  const sheetLine = phone && open ? allLines.find((l) => l.line_id === open) : undefined;

  const toggleMargin = () => {
    setShowMargin((v) => {
      try {
        window.localStorage.setItem(MARGIN_KEY, v ? "0" : "1");
      } catch {
        /* storage blocked: the choice lasts for this page only */
      }
      return !v;
    });
  };

  const scrollRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [listTop, setListTop] = useState(0);
  // The list starts below the findings box, which opens and closes: keep the virtualizer's offset in step.
  useLayoutEffect(() => {
    const list = listRef.current;
    const box = scrollRef.current?.querySelector("[data-testid=findings]");
    const measure = () => setListTop(list?.offsetTop ?? 0);
    measure();
    if (!box || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, [quote.findings.length]);
  // The virtualizer's API can't be memoized; React Compiler skips this component, which is what it needs.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => ({ group: 34, total: 44, empty: 120, line: 58, removed: 40 })[rows[i]?.kind ?? "line"],
    getItemKey: (i) => rows[i]?.key ?? i,
    overscan: 10,
    scrollMargin: listTop,
  });

  const requestFocus = useCallback((target: string, bbox: number[], mode: FocusRequest["mode"]) => {
    focusCount.current += 1;
    setFocus({ pageId: target, bbox, mode, nonce: focusCount.current });
  }, []);

  // 09 §7.1: a selected line moves the drawing to its page (the current one if the line is on it), and when the
  // drawing is zoomed in, centres it.
  const follow = useCallback(
    (id: string) => {
      const line = allLines.find((l) => l.line_id === id);
      const target = line ? pageForLine(line, pageId, quote.pages) : null;
      setShownFinding(null);
      if (!line || !target) return;
      if (target !== pageId) setPageId(target);
      else {
        const bbox = boxOnPage(line, target);
        if (bbox) requestFocus(target, bbox, "center");
      }
    },
    [allLines, pageId, quote.pages, requestFocus],
  );

  const select = useCallback(
    (id: string | null, focusRow = false) => {
      setSelected(id);
      if (!id) return;
      follow(id);
      const index = rows.findIndex((r) => r.key === id);
      if (index >= 0) virtual.scrollToIndex(index, { align: "auto" });
      if (focusRow) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-line="${id}"]`)?.focus());
    },
    [rows, virtual, follow],
  );
  const toggle = (id: string) => {
    setSelected(id);
    follow(id);
    setOpen((o) => (o === id ? null : id));
  };

  // "הצג בשרטוט" (09 §5.2, §6.4; prototype `showOnDrawing`): the line's page, framed on its component. On the phone
  // it also moves to the drawing tab and closes the sheet.
  const showOnDrawing = (line: QuoteLine) => {
    const target = pageForLine(line, pageId, quote.pages);
    const bbox = target ? boxOnPage(line, target) : null;
    if (!target || !bbox) return;
    setSelected(line.line_id);
    setShownFinding(null);
    setPageId(target);
    requestFocus(target, bbox, "frame");
    if (phone) {
      setOpen(null);
      setTab("drawing");
    }
  };

  const showFinding = (f: Finding) => {
    const box = findingBox(f);
    if (!box) return;
    setSelected(null);
    setShownFinding(box);
    setPageId(box.pageId);
    requestFocus(box.pageId, box.bbox, "frame");
    if (phone) setTab("drawing");
  };

  // A click on a box in the drawing selects its line (09 §7.1): in its panel, with the filter widened if it hid the
  // line, and the table scrolled to it. On the phone the line's sheet opens over the drawing.
  const pendingScroll = useRef<string | null>(null);
  const selectFromDrawing = (id: string) => {
    const idx = quote.panels.findIndex((p) => p.lines.some((l) => l.line_id === id));
    const line = allLines.find((l) => l.line_id === id);
    if (idx >= 0 && idx !== panelIdx) setPanelIdx(idx);
    if (line && !matches(line, filter)) setFilter("all");
    setSelected(id);
    setShownFinding(null);
    if (phone) setOpen(id);
    else pendingScroll.current = id;
  };
  useEffect(() => {
    const id = pendingScroll.current;
    if (!id) return;
    const index = rows.findIndex((r) => r.key === id);
    if (index < 0) return;
    pendingScroll.current = null;
    virtual.scrollToIndex(index, { align: "auto" });
  }, [rows, virtual, selected]);

  const selectPanel = (panelId: string) => {
    const idx = quote.panels.findIndex((p) => p.panel_id === panelId);
    if (idx < 0) return;
    setPanelIdx(idx);
    setOpen(null);
    setSelected(null);
  };

  // --- actions (09 §7) ---------------------------------------------------------------------------------------------

  const quoteId = quote.quote_id;
  const show = useCallback((q: Quote) => qc.setQueryData(["quote", quoteId], q), [qc, quoteId]);

  /** Runs an action; its toast offers "בטל" when it has an event (09 §7.11). Resolves true when the server took it. */
  const run = useCallback(
    async (call: () => Promise<ActionResult>, after?: (q: Quote) => void): Promise<boolean> => {
      setBusy(true);
      try {
        const done = await call();
        show(done.quote);
        const eventId = done.event_id;
        if (eventId)
          undo.record({
            label: done.message,
            undo: async () => {
              show((await undoAction(quoteId, eventId)).quote);
            },
          });
        else toast(done.message);
        after?.(done.quote);
        return true;
      } catch (e) {
        toast(e instanceof ApiError ? e.message : "לא הצלחנו לשמור. נסו שוב");
        if (e instanceof ApiError && e.status === 409) void qc.invalidateQueries({ queryKey: ["quote", quoteId] });
        return false;
      } finally {
        setBusy(false);
      }
    },
    [show, undo, toast, quoteId, qc],
  );

  const panelIds = useCallback(
    (q: Quote) => {
      const p = q.panels[Math.min(panelIdx, q.panels.length - 1)];
      return p ? buildRows(p, filter).flatMap((r) => (r.kind === "line" ? [r.key] : [])) : [];
    },
    [panelIdx, filter],
  );

  const act = useCallback(
    (line: QuoteLine, action: LineAction) =>
      run(
        () => lineAction(quoteId, line.line_id, action),
        (q) => {
          if (action.kind === "approve") {
            // 09 §7.2: on to the next line that still needs checking
            const lines = q.panels.flatMap((p) => p.lines);
            const next = nextToCheck(panelIds(q), lines, line.line_id);
            if (next) {
              setSelected(next);
              setOpen((o) => (o === line.line_id ? next : o));
            }
          } else if (action.kind === "delete") {
            setOpen((o) => (o === line.line_id ? null : o));
            setSelected((sel) => (sel === line.line_id ? null : sel));
          }
        },
      ),
    [run, quoteId, panelIds],
  );

  const dismiss = useCallback(
    (f: Finding, reason: DismissReason, text?: string) =>
      run(
        () => dismissFinding(quoteId, f.finding_id, reason, text),
        () => setDismissing(null),
      ),
    [run, quoteId],
  );

  /** The row's price cell (S23 decision 3): Enter saves it and moves on to the next line with no price. */
  const enterPrice = (line: QuoteLine, text: string) => {
    const amount = parseAmount(text);
    if (amount === null) {
      toast("הזינו מחיר ליחידה, במספרים");
      return;
    }
    const save = saveToList[line.line_id] !== false;
    void run(
      () => lineAction(quoteId, line.line_id, { kind: "price-entry", unit_price: amount, save }),
      (q) => {
        const lines = q.panels.flatMap((p) => p.lines);
        const next = nextUnpriced(panelIds(q), lines, line.line_id);
        if (!next) return;
        const index = rows.findIndex((r) => r.key === next);
        if (index >= 0) virtual.scrollToIndex(index, { align: "auto" });
        requestAnimationFrame(() => document.querySelector<HTMLInputElement>(`#price-${next}`)?.focus());
      },
    );
  };

  const detailActions = (line: QuoteLine): DetailActions => ({
    quoteId,
    locked,
    lineFloor: quote.line_floor,
    saveToList: saveToList[line.line_id] !== false,
    onSaveToList: (on) => setSaveToList((m) => ({ ...m, [line.line_id]: on })),
    onAction: act,
    onDismiss: dismiss,
    onPickProduct: (l) => setPicker({ kind: "missing", line: l }),
  });

  const page = quote.pages.find((p) => p.page_id === pageId) ?? quote.pages[0];
  const markable = canMark(page, locked);
  const drawn = (onPage: string, bbox: number[]) => {
    if (tooSmall(bbox)) toast("גררו מלבן סביב הרכיב");
    else setPicker({ kind: "mark", pageId: onPage, bbox });
  };
  const picked = (choice: ProductChoice) => {
    const p = picker;
    setPicker(null);
    if (!p) return;
    if (p.kind === "missing") {
      void act(p.line, { kind: "resolve", ref: choice.ref });
      return;
    }
    void run(
      () =>
        markComponent(quoteId, { page_id: p.pageId, bbox: p.bbox, ref: choice.ref, panel_id: panel?.panel_id ?? null }),
      (q) => {
        setDrawing(false);
        // the new line, selected: the one manual line whose box is the rectangle
        const added = q.panels
          .flatMap((x) => x.lines)
          .find(
            (l) => l.line_type === "manual" && l.boxes.some((b) => b.page_id === p.pageId && sameBox(b.bbox, p.bbox)),
          );
        if (added) setSelected(added.line_id);
      },
    );
  };

  const restore = (ids: string[]) => void run(() => restoreLines(quoteId, ids));

  const send = async () => {
    setBusy(true);
    try {
      show(await sendQuote(quoteId));
      undoStackFor(quoteId).clear(); // nothing before sending can be undone (09 §7.11)
      setSending(false);
      toast(`גרסה ${quote.version} נשלחה ונעולה`);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "לא הצלחנו לשלוח. נסו שוב");
    } finally {
      setBusy(false);
    }
  };

  const openNext = async () => {
    try {
      show(await openNextVersion(quoteId));
      toast(`נפתחה גרסה ${quote.version + 1}. הגרסה הקודמת נשמרה`);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "לא הצלחנו לפתוח גרסה חדשה");
    }
  };

  const freshCount = allLines.filter((l) => l.fresh_price != null).length;
  const askRecalc = async () => {
    try {
      setRecalc(await previewRecalculation(quoteId));
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "לא הצלחנו לחשב מחדש");
    }
  };
  const applyRecalc = async () => {
    try {
      show(await recalculateQuote(quoteId));
      setRecalc(null);
      toast("ההצעה חושבה מחדש לפי המחירון");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "לא הצלחנו לחשב מחדש");
    }
  };

  const keyAction = useRef<(e: KeyboardEvent) => boolean>(() => false);
  keyAction.current = (e: KeyboardEvent) => {
    if (locked || busy || !selected) return false;
    const line = allLines.find((l) => l.line_id === selected);
    if (!line) return false;
    if (e.key === "Enter" && !line.approved && line.line_type !== "missing" && line.line_type !== "manual") {
      void act(line, { kind: "approve" });
      return true;
    }
    if (e.key === "Delete" || e.key === "Backspace") {
      void act(line, { kind: "delete" });
      return true;
    }
    const n = ["1", "2", "3"].indexOf(e.key);
    if (n >= 0 && line.line_type === "missing" && e.code.startsWith("Digit")) {
      // 09 §8: 1–3 pick a missing line's product, once the detail has fetched them
      const found = qc.getQueryData<ProductChoice[]>(["candidates", quoteId, line.line_id]);
      const choice = found?.[n];
      if (choice) void act(line, { kind: "resolve", ref: choice.ref });
      return !!choice;
    }
    if (n >= 0 && line.alternatives[n] && e.code.startsWith("Digit")) {
      void act(line, { kind: "alternative", index: n });
      return true;
    }
    return false;
  };

  // 09 §8, on the desktop, when the focus is not in a text field. Enter approves (S09 decision 9), 1–3 choose an
  // alternative, Delete deletes.
  // Undo (Ctrl+Z / ⌘Z) works on any keyboard, the phone's too (09 §7.11).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      if (isUndoKey(e)) {
        e.preventDefault();
        void undo.undo();
        return;
      }
      if (e.key === "/" && chatOnRef.current) {
        // 09 §8, prototype line 1584: "/" moves the focus to the chat's field
        e.preventDefault();
        if (phone) setTab("chat");
        else setChatOpen(true);
        requestAnimationFrame(() => chatInput.current?.focus());
        return;
      }
      if (e.key === "Escape" && drawingRef.current) {
        // 09 §8: Esc leaves draw mode before it closes a sheet or drops the selection
        setDrawing(false);
        return;
      }
      if (phone) return;
      if (keyAction.current(e)) {
        e.preventDefault();
        return;
      }
      if (e.key === "PageDown" || e.key === "PageUp") {
        e.preventDefault();
        const next = stepPage(quote.pages, pageId, e.key === "PageDown" ? 1 : -1);
        if (next) setPageId(next);
      } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        select(stepLine(lineIds, selected, e.key === "ArrowDown" ? 1 : -1), true);
      } else if (e.key === " " && selected) {
        e.preventDefault();
        setOpen((o) => (o === selected ? null : selected));
      } else if (e.key === "Escape") {
        if (open) setOpen(null);
        else {
          setSelected(null);
          setShownFinding(null);
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [phone, lineIds, selected, open, select, undo, quote.pages, pageId]);
  const drawingRef = useRef(drawing);
  const chatOnRef = useRef(chatOn);
  useEffect(() => {
    drawingRef.current = drawing;
    chatOnRef.current = chatOn;
  });

  // --- the chat (08, 09 §6.7) ------------------------------------------------------------------------------------
  const chatUi = {
    panel_id: panel?.panel_id ?? null,
    selected_line_ids: selected ? [selected] : [],
    active_filter: filter === "red" || filter === "yellow" || filter === "green" ? filter : null,
  };
  // A line chip: the line selected in its panel; on the phone, the lines tab with its sheet open (09 §5.2)
  const chatSelect = (id: string) => {
    selectFromDrawing(id);
    if (phone) setTab("lines");
  };
  // 08 §6.4 `focus`: the component framed on its page, its line selected. Behind the desktop drawer until it closes.
  const frameInstance = (inst: ChatInstance) => {
    if (inst.line_id) setSelected(inst.line_id);
    setShownFinding(null);
    setPageId(inst.page_id);
    requestFocus(inst.page_id, inst.bbox, "frame");
  };
  // the answer's "בשרטוט" chip: the drawing in view, on the phone its tab and on the desktop without the drawer
  const chatShowInstance = (inst: ChatInstance) => {
    frameInstance(inst);
    if (phone) setTab("drawing");
    else setChatOpen(false);
  };
  const chatFocus = (f: ChatFocus) => {
    const first = f.instances?.[0];
    if (first) {
      frameInstance(first);
      return;
    }
    const status = f.statuses?.length === 1 ? f.statuses[0] : null;
    if (status === "red" || status === "yellow" || status === "green") setFilter(status);
    if (f.panelId && !f.lineIds.length) selectPanel(f.panelId);
    if (f.lineIds[0]) chatSelect(f.lineIds[0]);
    else if (phone && status) setTab("lines");
  };
  const chatApplied = (done: { quote: Quote; message: string; event_id?: string | null }) => {
    show(done.quote);
    const eventId = done.event_id;
    if (eventId)
      undo.record({
        label: done.message,
        undo: async () => {
          show((await undoAction(quoteId, eventId)).quote);
          void qc.invalidateQueries({ queryKey: ["chat", quoteId] });
        },
      });
    else toast(done.message);
  };
  const chatPanel = chatOn ? (
    <ChatPanel
      quote={quote}
      ui={chatUi}
      inputRef={chatInput}
      onClose={phone ? undefined : () => setChatOpen(false)}
      onSelectLine={chatSelect}
      onFocus={chatFocus}
      onShowInstance={chatShowInstance}
      onApplied={chatApplied}
      toast={toast}
    />
  ) : null;

  const kind = quote.input_kind ? INPUT_KINDS[quote.input_kind]?.[0] : null;
  const sub = [quote.drawing_number, kind, `גרסה ${quote.version}`, quote.status === "sent" ? "נשלחה" : "טיוטה"];

  return (
    <div className="review">
      <div className="rv-head">
        <Link className="btn ghost sm" to="/home" aria-label="חזרה">
          <Icon name="back" />
        </Link>
        <div style={{ display: "grid", minWidth: 0 }}>
          <h1>{quote.name}</h1>
          <span className="small muted">
            {sub.filter(Boolean).map((part, i) => (
              <span key={i}>
                {i ? " · " : ""}
                {i === 0 ? <span dir="ltr">{part}</span> : part}
              </span>
            ))}
          </span>
        </div>
        <span className="spacer" />
        <div className="rv-totals" data-testid="rv-totals">
          <span className="small muted">לפני מע"מ</span>
          <b className="num">{shekels(t.net_total)}</b>
          {t.margin_pct != null ? (
            <span className={`chip ${belowFloor(t.margin_pct, quote.quote_floor) ? "warn" : "ok"}`}>
              רווח {percent(t.margin_pct)}
            </span>
          ) : null}
          {t.unpriced_count ? <span className="chip bad">{t.unpriced_count} חסרים</span> : null}
        </div>
        <button
          type="button"
          className="btn sm"
          title="בטל (Ctrl+Z)"
          aria-label="בטל את הפעולה האחרונה"
          data-testid="undo-last"
          disabled={!undo.canUndo}
          onClick={() => void undo.undo()}
        >
          <Icon name="undo" />
        </button>
        {exportOn ? (
          <button type="button" className="btn sm" data-testid="export" onClick={() => setExporting(true)}>
            <Icon name="down" />
            הורדה
          </button>
        ) : null}
        {chatOn ? (
          <button
            type="button"
            className="btn sm chat-toggle"
            data-testid="chat-toggle"
            aria-pressed={chatOpen}
            onClick={() => setChatOpen((o) => !o)}
          >
            <Icon name="chat" />
            צ'אט
          </button>
        ) : null}
        {locked ? (
          <button type="button" className="btn primary sm" data-testid="newver" onClick={() => void openNext()}>
            פתח גרסה {quote.version + 1}
          </button>
        ) : (
          <button type="button" className="btn primary sm" data-testid="send" onClick={() => setSending(true)}>
            <Icon name="send" />
            אשר ושלח
          </button>
        )}
      </div>
      {locked ? (
        <div className="locked" data-testid="locked">
          <Icon name="lock" />
          <span>גרסה {quote.version} נשלחה ללקוח ונעולה. כדי לשנות, פותחים גרסה חדשה.</span>
        </div>
      ) : null}
      <div className="rv-tabs" role="tablist" aria-label="תצוגה">
        {(
          [
            ["lines", "שורות"],
            ["drawing", "שרטוט"],
            ["chat", "צ'אט"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            aria-pressed={tab === k}
            onClick={() => setTab(k)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="rv-body" data-tab={tab}>
        <section className={`pane lines-pane${showMargin ? " with-margin" : ""}`} aria-label="שורות ההצעה">
          {tabs.length ? (
            <div className="panel-tabs" role="tablist" aria-label="לוחות">
              {tabs.map((p, i) => (
                <button
                  key={p.panelId ?? i}
                  type="button"
                  role="tab"
                  aria-selected={i === panelIdx}
                  aria-pressed={i === panelIdx}
                  onClick={() => {
                    setPanelIdx(i);
                    setOpen(null);
                    setSelected(null);
                  }}
                >
                  {p.name}
                  {p.open ? <span className="chip warn num">{p.open}</span> : null}
                </button>
              ))}
            </div>
          ) : null}
          <div className="lines-tools">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className="fchip"
                data-testid={`filter-${f.key}`}
                aria-pressed={filter === f.key}
                onClick={() => setFilter((cur) => nextFilter(cur, f.key))}
              >
                {f.swatch ? <span className={`sw ${f.swatch}`} aria-hidden="true" /> : null}
                {f.label}
                <span className="num muted">{counts[f.key]}</span>
              </button>
            ))}
            <span className="spacer" />
            <button type="button" className="fchip" aria-pressed={showMargin} onClick={toggleMargin}>
              רווחיות
            </button>
            {!locked && freshCount ? (
              <button type="button" className="fchip" data-testid="recalc" onClick={() => void askRecalc()}>
                {freshCount === 1 ? "מחיר חדש במחירון" : `${freshCount} מחירים חדשים במחירון`}
              </button>
            ) : null}
            {quote.coverage_pct != null && quote.coverage_pct < 100 ? (
              <span className="small muted">
                כיסוי מחירון <b className="num">{quote.coverage_pct}%</b>
              </span>
            ) : null}
          </div>
          {quote.first_quote ? (
            <div className="card first-quote" role="status" data-testid="first-quote">
              <b>זו ההצעה הראשונה שלכם.</b>
              <span className="small">המחירים שתקלידו יישמרו וישמשו בכל ההצעות הבאות.</span>
            </div>
          ) : null}
          <div className="rv-progress" data-testid="progress">
            <span>{prog.text}</span>
            <div
              className="meter"
              role="progressbar"
              aria-label="שורות מוכנות"
              aria-valuemin={0}
              aria-valuemax={prog.total}
              aria-valuenow={prog.ready}
            >
              <i style={{ width: `${prog.pct}%` }} />
            </div>
          </div>
          <div className="lines-scroll" ref={scrollRef} data-testid="lines-scroll">
            <Findings
              findings={quote.findings}
              onShow={showFinding}
              locked={locked}
              dismissing={dismissing}
              onDismissing={setDismissing}
              onDismiss={dismiss}
              onOnlyRed={() => setFilter("red")}
              onOpenLine={(id) => {
                setFilter("all");
                setSelected(id);
                setOpen(id);
                follow(id);
              }}
            />
            <div className="lh" aria-hidden="true">
              <span />
              <span />
              <span>מוצר</span>
              <span className="q">כמות</span>
              <span className="p">ליחידה</span>
              {showMargin ? <span className="mg">רווח</span> : null}
              <span className="t">סה"כ</span>
            </div>
            <div ref={listRef} role="list" style={{ height: virtual.getTotalSize(), position: "relative" }}>
              {virtual.getVirtualItems().map((item) => {
                const row = rows[item.index];
                if (!row) return null;
                return (
                  <div
                    key={item.key}
                    role="listitem"
                    data-index={item.index}
                    ref={virtual.measureElement}
                    style={{
                      position: "absolute",
                      top: 0,
                      insetInlineStart: 0,
                      width: "100%",
                      transform: `translateY(${item.start - virtual.options.scrollMargin}px)`,
                    }}
                  >
                    <RowView
                      row={row}
                      findings={quote.findings}
                      selected={selected}
                      open={phone ? null : open}
                      showMargin={showMargin}
                      locked={locked}
                      onToggle={toggle}
                      onShowAll={() => setFilter("all")}
                      onShowOnDrawing={showOnDrawing}
                      onEnterPrice={enterPrice}
                      onRestore={restore}
                      detailActions={detailActions}
                    />
                  </div>
                );
              })}
            </div>
            {quote.derived_note ? (
              <div className="small muted" style={{ padding: 14 }} data-testid="derived-note">
                {quote.derived_note} <Link to="/prefs">שינוי</Link>
              </div>
            ) : null}
          </div>
          <div className="lines-foot" data-testid="lines-foot">
            <span>
              סה"כ <b className="num">{shekels(t.net_total)}</b>
            </span>
            <span className="muted">
              מע"מ {percent(t.vat_rate)} <span className="num">{shekels(t.vat)}</span>
            </span>
            <span>
              כולל מע"מ <b className="num">{shekels(t.gross_total)}</b>
            </span>
            {quote.can_see_costs ? (
              <span className={belowFloor(t.margin_pct, quote.quote_floor) ? "warn-t" : undefined}>
                רווח <b className="num">{shekels(t.margin_abs)}</b>{" "}
                <span className="num">({percent(t.margin_pct)})</span>
              </span>
            ) : null}
            {t.uncosted_count ? (
              <span className="small muted">
                {t.uncosted_count === 1 ? "שורה אחת בלי עלות לא נכללת" : `${t.uncosted_count} שורות בלי עלות לא נכללות`}
              </span>
            ) : null}
            <span className="spacer" />
            <span className="small muted kbd-hint">
              <span className="kbd">↑</span> <span className="kbd">↓</span> ניווט · <span className="kbd">Enter</span>{" "}
              אישור · <span className="kbd">Space</span> פרטים · <span className="kbd">1</span>–
              <span className="kbd">3</span> חלופה · <span className="kbd">PgDn</span> עמוד ·{" "}
              <span className="kbd">Esc</span> סגירה
            </span>
          </div>
        </section>
        <section className="pane drawing-pane" aria-label="שרטוט">
          <DrawingPane
            pages={quote.pages}
            overlays={(page) => overlays(quote, page, { selected, filter, activePanelId: panel?.panel_id ?? null })}
            pageId={pageId}
            onPage={(id: string) => {
              setPageId(id);
              setShownFinding(null);
            }}
            activePanelId={panel?.panel_id ?? null}
            focus={focus}
            finding={shownFinding}
            onSelectLine={selectFromDrawing}
            onSelectPanel={selectPanel}
            mark={{ available: markable, on: drawing, onToggle: () => setDrawing((d) => !d), onDrawn: drawn }}
            unresolved={
              unresolvedFlag
                ? { spots: unresolved.data ?? [], on: showUnresolved, onToggle: () => setShowUnresolved((v) => !v) }
                : undefined
            }
          />
        </section>
        {chatPanel && (phone ? tab === "chat" : chatOpen) ? (
          chatPanel
        ) : chatOn ? null : (
          <section className="pane chat-pane" aria-label="צ'אט">
            <div className="drawing-soon">
              <span className="small">הצ'אט כבוי בהגדרות</span>
            </div>
          </section>
        )}
      </div>
      {sheetLine ? (
        <Modal onClose={() => setOpen(null)} labelledBy="sheet-title" className="sheet" backdropClassName="sheet-bg">
          <div className="row">
            <h2 id="sheet-title" style={{ fontSize: 16, margin: 0, flex: 1 }}>
              {sheetLine.description}
            </h2>
            <button type="button" className="btn ghost sm" aria-label="סגירה" onClick={() => setOpen(null)}>
              <Icon name="x" />
            </button>
          </div>
          <LineDetail
            line={sheetLine}
            findings={quote.findings}
            onShowOnDrawing={showOnDrawing}
            actions={detailActions(sheetLine)}
          />
        </Modal>
      ) : null}
      {picker ? (
        <ProductPicker
          quoteId={quoteId}
          title={picker.kind === "mark" ? "איזה רכיב סימנתם?" : "בחירת מוצר לשורה"}
          onPick={picked}
          onClose={() => setPicker(null)}
        />
      ) : null}
      {sending ? (
        <SendDialog quote={quote} busy={busy} onSend={() => void send()} onClose={() => setSending(false)} />
      ) : null}
      {exporting && exportOn ? <ExportModal quote={quote} onClose={() => setExporting(false)} /> : null}
      {recalc ? (
        <RecalcDialog diff={recalc} onApply={() => void applyRecalc()} onClose={() => setRecalc(null)} />
      ) : null}
    </div>
  );
}

function Findings(props: {
  findings: Finding[];
  onShow: (f: Finding) => void;
  locked: boolean;
  dismissing: string | null;
  onDismissing: (id: string | null) => void;
  onDismiss: (f: Finding, reason: DismissReason, text?: string) => Promise<boolean>;
  onOnlyRed: () => void;
  onOpenLine: (lineId: string) => void;
}) {
  const { findings } = props;
  if (!findings.length) return null;
  // prototype `f-*`: "הצג רק אותן" for the lines with no price, "פתח את השורה", "בשרטוט" (S11), and a dismissal with
  // a reason (09 §7.7) for any finding a price does not answer
  return (
    <details className="findings" open data-testid="findings">
      <summary>
        {findings.length} ממצאים
        <span className="spacer" />
        <span className="small muted">מהבודק</span>
      </summary>
      {findings.map((f) => (
        <div key={f.finding_id} className="finding" data-testid="finding">
          <span className={`sev ${f.severity}`} aria-hidden="true" />
          <div style={{ display: "grid", gap: 3 }}>
            <b>{f.title ?? f.message}</b>
            {f.title ? <span className="small muted">{f.message}</span> : null}
          </div>
          <div className="acts">
            {f.code === "missing_cost" ? (
              <button type="button" className="btn sm" data-testid="f-onlyred" onClick={props.onOnlyRed}>
                הצג רק אותן
              </button>
            ) : null}
            {f.source !== "pricing" && f.line_ids.length === 1 && f.line_ids[0] ? (
              <button
                type="button"
                className="btn sm"
                data-testid="f-goto"
                onClick={() => props.onOpenLine(f.line_ids[0] ?? "")}
              >
                פתח את השורה
              </button>
            ) : null}
            {!props.locked && f.source !== "pricing" ? (
              <button
                type="button"
                className="btn sm"
                data-testid="f-ignore"
                aria-expanded={props.dismissing === f.finding_id}
                onClick={() => props.onDismissing(props.dismissing === f.finding_id ? null : f.finding_id)}
              >
                דחה…
              </button>
            ) : null}
            {findingBox(f) ? (
              <button type="button" className="btn ghost sm" data-testid="f-show" onClick={() => props.onShow(f)}>
                <Icon name="eye" />
                בשרטוט
              </button>
            ) : null}
          </div>
          {props.dismissing === f.finding_id ? (
            <div style={{ gridColumn: 2 }}>
              <DismissControl finding={f} onDismiss={props.onDismiss} />
            </div>
          ) : null}
        </div>
      ))}
    </details>
  );
}

function RowView(props: {
  row: Row;
  findings: Finding[];
  selected: string | null;
  open: string | null;
  showMargin: boolean;
  locked: boolean;
  onToggle: (id: string) => void;
  onShowAll: () => void;
  onShowOnDrawing: (line: QuoteLine) => void;
  onEnterPrice: (line: QuoteLine, text: string) => void;
  onRestore: (ids: string[]) => void;
  detailActions: (line: QuoteLine) => DetailActions;
}) {
  const { row } = props;
  if (row.kind === "group") return <div className="grp">{row.label}</div>;
  if (row.kind === "total")
    return (
      <div className="ln-sum" data-testid="panel-total">
        <span>{row.label}</span>
        <span className="num">{shekels(row.amount)}</span>
      </div>
    );
  if (row.kind === "empty")
    return (
      <div className="lines-empty">
        <span>אין שורות שמתאימות לסינון</span>
        <button type="button" className="btn sm" onClick={props.onShowAll}>
          הצג הכל
        </button>
      </div>
    );
  if (row.kind === "removed")
    return (
      <div className="ln-removed" data-testid="removed">
        <span>{row.lineIds.length === 1 ? "פריט נלווה אחד הוסר" : `${row.lineIds.length} פריטים נלווים הוסרו`}</span>
        {props.locked ? null : (
          <button type="button" className="btn ghost sm" onClick={() => props.onRestore(row.lineIds)}>
            החזר
          </button>
        )}
      </div>
    );
  return (
    <LineRow
      line={row.line}
      child={row.child}
      findings={props.findings}
      selected={props.selected === row.line.line_id}
      open={props.open === row.line.line_id}
      showMargin={props.showMargin}
      locked={props.locked}
      onToggle={props.onToggle}
      onShowOnDrawing={props.onShowOnDrawing}
      onEnterPrice={props.onEnterPrice}
      detailActions={props.detailActions}
    />
  );
}

function LineRow(props: {
  line: QuoteLine;
  child: boolean;
  findings: Finding[];
  selected: boolean;
  open: boolean;
  showMargin: boolean;
  locked: boolean;
  onToggle: (id: string) => void;
  onShowOnDrawing: (line: QuoteLine) => void;
  onEnterPrice: (line: QuoteLine, text: string) => void;
  detailActions: (line: QuoteLine) => DetailActions;
}) {
  const { line } = props;
  const mark = statusMark(line);
  const tone = { green: "g", yellow: "y", red: "r" }[line.status];
  const priceCell = !props.locked && takesPrice(line);
  return (
    <>
      <div
        className={`ln ${tone}${props.child ? " child" : ""}`}
        role="button"
        tabIndex={props.selected ? 0 : -1}
        data-line={line.line_id}
        data-testid="line"
        aria-current={props.selected ? "true" : undefined}
        aria-expanded={props.open}
        onClick={(e) => {
          if ((e.target as HTMLElement).closest("input")) return; // typing a price is not a click on the row
          props.onToggle(line.line_id);
        }}
      >
        <span className="stripe" aria-hidden="true" />
        <StatusIcon shape={mark.shape} label={mark.label} />
        <div style={{ minWidth: 0 }}>
          <div className="name">{line.description}</div>
          <div className="sub">
            {compactDesignators(line.designators).map((d) => (
              <span key={d} className="des">
                {d}
              </span>
            ))}
            {[...reasonChips(line, props.findings), ...priceChips(line, props.locked)].map((c) => (
              <span key={c.text} className={`chip ${c.tone}`}>
                {c.text}
              </span>
            ))}
            {line.note ? <span className="small muted">{line.note}</span> : null}
            <span className="qp small muted num">{line.included ? "כלול" : qtyTimesPrice(line)}</span>
          </div>
        </div>
        <span className="q num">{qtyText(line.qty)}</span>
        <span className="p">
          {line.included ? (
            <span className="small muted">כלול</span>
          ) : priceCell ? (
            <input
              className="price-in"
              id={`price-${line.line_id}`}
              data-testid="price-in"
              inputMode="decimal"
              placeholder="מחיר"
              aria-label={`מחיר ליחידה ל${line.description}`}
              onKeyDown={(e) => {
                e.stopPropagation(); // the row's own keys (Enter approves) are not the cell's
                if (e.key === "Enter") {
                  e.preventDefault();
                  props.onEnterPrice(line, e.currentTarget.value);
                }
              }}
            />
          ) : (
            shekels(line.unit_price)
          )}
        </span>
        {props.showMargin ? (
          <span className={`mg num${line.below_floor ? " warn-t" : ""}`}>
            {line.included ? "" : line.margin_pct == null ? "—" : percent(line.margin_pct)}
          </span>
        ) : null}
        <span className="t num">{line.included ? "" : shekels(line.line_total)}</span>
      </div>
      {props.open ? (
        <div style={{ padding: "0 14px 8px" }}>
          <LineDetail
            line={line}
            findings={props.findings}
            onShowOnDrawing={props.onShowOnDrawing}
            actions={props.detailActions(line)}
          />
        </div>
      ) : null}
    </>
  );
}

/** 09 §7.12, prototype `send`: the one dialog that asks before acting, since sending cannot be undone. */
function SendDialog(props: { quote: Quote; busy: boolean; onSend: () => void; onClose: () => void }) {
  const { quote } = props;
  const t = quote.totals;
  const sum = sendSummary(quote);
  return (
    <Modal onClose={props.onClose} labelledBy="send-title">
      <h2 id="send-title">לשלוח את גרסה {quote.version}?</h2>
      <dl className="kv">
        <dt>לפני מע"מ</dt>
        <dd className="num">
          <b>{shekels(t.net_total)}</b>
        </dd>
        <dd />
        <dt>כולל מע"מ</dt>
        <dd className="num">{shekels(t.gross_total)}</dd>
        <dd />
        {quote.can_see_costs && t.margin_pct != null ? (
          <>
            <dt>רווח</dt>
            <dd className="num">
              {shekels(t.margin_abs)} ({percent(t.margin_pct)})
            </dd>
            <dd />
          </>
        ) : null}
      </dl>
      {sum.unpriced ? (
        <div className="small alert-bad">
          {sum.unpriced === 1 ? "שורה אחת בלי מחיר לא נכללת" : `${sum.unpriced} שורות בלי מחיר לא נכללות`} בסכום, ותופיע
          בהצעה בלי סכום. מומלץ להשלים לפני השליחה.
        </div>
      ) : null}
      {sum.red && sum.red !== sum.unpriced ? <div className="small alert-bad">{sum.red} שורות אדומות.</div> : null}
      {sum.yellow ? <div className="small alert-warn">{sum.yellow} שורות צהובות לא אושרו.</div> : null}
      <span className="small muted">הלקוח מקבל תיאור, כמות, מחיר וסכום. לא עלות, לא רווח ולא צבעים.</span>
      <div className="row">
        <button type="button" className="btn primary" data-testid="dosend" disabled={props.busy} onClick={props.onSend}>
          {sum.red || sum.yellow ? "שלח בכל זאת" : "שלח ללקוח"}
        </button>
        <button type="button" className="btn" onClick={props.onClose}>
          חזרה להצעה
        </button>
      </div>
    </Modal>
  );
}

/** 07 §7.2.3: "חישוב מחדש" shows what changes before it is applied. */
function RecalcDialog(props: { diff: Recalculation; onApply: () => void; onClose: () => void }) {
  const { diff } = props;
  const changed = diff.lines.filter((x) => x.change === "changed");
  return (
    <Modal onClose={props.onClose} labelledBy="recalc-title" className="wide">
      <h2 id="recalc-title">לעדכן את ההצעה לפי המחירון?</h2>
      {changed.length ? (
        <dl className="kv">
          {changed.map((x) => (
            <Fragment key={x.key}>
              <dt>{x.description}</dt>
              <dd className="num">
                {shekels((x.before?.unit_price as string | undefined) ?? null)} ←{" "}
                {shekels((x.after?.unit_price as string | undefined) ?? null)}
              </dd>
              <dd className="num small muted">{shekels(x.delta ?? null)}</dd>
            </Fragment>
          ))}
        </dl>
      ) : (
        <span className="small muted">אין שינוי במחירים.</span>
      )}
      <span className="small">
        לפני מע"מ: <b className="num">{shekels(diff.net_before)}</b> ← <b className="num">{shekels(diff.net_after)}</b>
      </span>
      <div className="row">
        <button type="button" className="btn primary" data-testid="dorecalc" onClick={props.onApply}>
          עדכן את כל השורות
        </button>
        <button type="button" className="btn" onClick={props.onClose}>
          ביטול
        </button>
      </div>
    </Modal>
  );
}

const SHAPES: Record<Shape, ReactNode> = {
  check: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.6 2.6L16 9.5" />
    </>
  ),
  triangle: (
    <>
      <path d="M12 3.5L21.5 20h-19z" />
      <path d="M12 10v4.5M12 17.4v.1" />
    </>
  ),
  cross: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </>
  ),
  box: (
    <>
      <path d="M4 8l8-4 8 4v8l-8 4-8-4z" />
      <path d="M4 8l8 4 8-4M12 12v8" />
    </>
  ),
};

/** The status shape beside the stripe (S09 decision 3): a screen reader hears its label (09 §13). */
function StatusIcon({ shape, label }: { shape: Shape; label: string }) {
  return (
    <svg
      className="ln-st"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={label}
      data-shape={shape}
    >
      {SHAPES[shape]}
    </svg>
  );
}

function sameBox(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((v, i) => Math.abs(v - (b[i] ?? 0)) < 0.01);
}
