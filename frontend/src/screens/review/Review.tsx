import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { Link, useParams } from "react-router";

import { ApiError, fetchQuote, type Finding, type Quote, type QuoteLine } from "../../api/client";
import { Shell } from "../../shell/Shell";
import { MOBILE_MAX_PX } from "../../theme/tokens";
import { Icon } from "../../ui/Icon";
import { Modal } from "../../ui/Modal";
import { INPUT_KINDS } from "../newQuote/model";
import { LineDetail } from "./LineDetail";
import {
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
} from "./model";

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
 * The review screen, S09 part (09 §5–6.4, §8, prototype `vReview`): header, filters, findings, the grouped lines
 * table and line detail. The drawing pane is S11, actions S23, chat S25.
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
    estimateSize: (i) => ({ group: 34, total: 44, empty: 120, line: 58 })[rows[i]?.kind ?? "line"],
    getItemKey: (i) => rows[i]?.key ?? i,
    overscan: 10,
    scrollMargin: listTop,
  });

  const select = useCallback(
    (id: string | null, focus = false) => {
      setSelected(id);
      if (!id) return;
      const index = rows.findIndex((r) => r.key === id);
      if (index >= 0) virtual.scrollToIndex(index, { align: "auto" });
      if (focus) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-line="${id}"]`)?.focus());
    },
    [rows, virtual],
  );
  const toggle = (id: string) => {
    setSelected(id);
    setOpen((o) => (o === id ? null : id));
  };

  // 09 §8, on the desktop, when the focus is not in a text field. Enter waits for "approve" (S23, decision 9).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (phone || e.defaultPrevented) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        select(stepLine(lineIds, selected, e.key === "ArrowDown" ? 1 : -1), true);
      } else if (e.key === " " && selected) {
        e.preventDefault();
        setOpen((o) => (o === selected ? null : selected));
      } else if (e.key === "Escape") {
        if (open) setOpen(null);
        else setSelected(null);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [phone, lineIds, selected, open, select]);

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
          {t.margin_pct != null ? <span className="chip ok">רווח {percent(t.margin_pct)}</span> : null}
          {t.unpriced_count ? <span className="chip bad">{t.unpriced_count} חסרים</span> : null}
        </div>
      </div>
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
            {quote.coverage_pct != null && quote.coverage_pct < 100 ? (
              <span className="small muted">
                כיסוי מחירון <b className="num">{quote.coverage_pct}%</b>
              </span>
            ) : null}
          </div>
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
            <Findings findings={quote.findings} />
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
                      onToggle={toggle}
                      onShowAll={() => setFilter("all")}
                    />
                  </div>
                );
              })}
            </div>
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
            <span>
              רווח <b className="num">{shekels(t.margin_abs)}</b> <span className="num">({percent(t.margin_pct)})</span>
            </span>
            {t.uncosted_count ? (
              <span className="small muted">
                {t.uncosted_count === 1 ? "שורה אחת בלי עלות לא נכללת" : `${t.uncosted_count} שורות בלי עלות לא נכללות`}
              </span>
            ) : null}
            <span className="spacer" />
            <span className="small muted kbd-hint">
              <span className="kbd">↑</span> <span className="kbd">↓</span> ניווט · <span className="kbd">Space</span>{" "}
              פרטים · <span className="kbd">Esc</span> סגירה
            </span>
          </div>
        </section>
        <section className="pane drawing-pane" aria-label="שרטוט">
          <div className="drawing-soon">
            <b>השרטוט יוצג כאן</b>
            <span className="small">סימון השורות על השרטוט יגיע בקרוב</span>
          </div>
        </section>
        <section className="pane chat-pane" aria-label="צ'אט">
          <div className="drawing-soon">
            <span className="small">הצ'אט יגיע בקרוב</span>
          </div>
        </section>
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
          <LineDetail line={sheetLine} findings={quote.findings} />
        </Modal>
      ) : null}
    </div>
  );
}

function Findings({ findings }: { findings: Finding[] }) {
  if (!findings.length) return null;
  // Read-only until S23 (dismiss) and S11 (show on drawing), S09 decision 11.
  return (
    <details className="findings" open data-testid="findings">
      <summary>
        {findings.length} ממצאים
        <span className="spacer" />
        <span className="small muted">מהבודק</span>
      </summary>
      {findings.map((f) => (
        <div key={f.finding_id} className="finding">
          <span className={`sev ${f.severity}`} aria-hidden="true" />
          <div style={{ display: "grid", gap: 3 }}>
            <b>{f.title ?? f.message}</b>
            {f.title ? <span className="small muted">{f.message}</span> : null}
          </div>
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
  onToggle: (id: string) => void;
  onShowAll: () => void;
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
  return (
    <LineRow
      line={row.line}
      child={row.child}
      findings={props.findings}
      selected={props.selected === row.line.line_id}
      open={props.open === row.line.line_id}
      showMargin={props.showMargin}
      onToggle={props.onToggle}
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
  onToggle: (id: string) => void;
}) {
  const { line } = props;
  const mark = statusMark(line);
  const tone = { green: "g", yellow: "y", red: "r" }[line.status];
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
        onClick={() => props.onToggle(line.line_id)}
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
            {reasonChips(line, props.findings).map((c) => (
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
          {line.included ? <span className="small muted">כלול</span> : shekels(line.unit_price)}
        </span>
        {props.showMargin ? (
          <span className="mg num">
            {line.included ? "" : line.margin_pct == null ? "—" : percent(line.margin_pct)}
          </span>
        ) : null}
        <span className="t num">{line.included ? "" : shekels(line.line_total)}</span>
      </div>
      {props.open ? (
        <div style={{ padding: "0 14px 8px" }}>
          <LineDetail line={line} findings={props.findings} />
        </div>
      ) : null}
    </>
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
