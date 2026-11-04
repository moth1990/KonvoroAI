import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import {
  missingCandidates,
  type DismissReason,
  type EditableAttribute,
  type Finding,
  type LineAction,
  type QuoteLine,
} from "../../api/client";
import { Icon } from "../../ui/Icon";
import { Modal } from "../../ui/Modal";
import {
  attributeChoice,
  attributeLabel,
  attributeValue,
  choiceMeta,
  discountFraction,
  lineFindings,
  missingText,
  parseAmount,
  percent,
  priceSourceText,
  qtyText,
  shekels,
  sourceText,
} from "./model";

/** What the detail can do (S23, S23b). Without it the detail is read-only, as on a sent version. */
export interface DetailActions {
  quoteId: string;
  locked: boolean;
  lineFloor: string | null;
  /** "שמור למחירון להצעות הבאות" for this line's price cell (prototype `savelist`), on unless turned off. */
  saveToList: boolean;
  onSaveToList: (on: boolean) => void;
  /** Resolves true when the server took it. */
  onAction: (line: QuoteLine, action: LineAction) => Promise<boolean>;
  onDismiss: (finding: Finding, reason: DismissReason, text?: string) => Promise<boolean>;
  /** "מוצר אחר…": the product picker, for this missing line (09 §6.4). */
  onPickProduct: (line: QuoteLine) => void;
}

/**
 * Line detail (09 §6.4, prototype `lineDetail`): what the drawing says, where each value comes from, why, the price
 * and its source, cost and margin, the line's findings and its alternatives, and since S23 what can be done about
 * each: a price ("לעדכן גם במחירון?"), a cost, a supplier, a finding dismissed with a reason, an alternative, the
 * quantity, approve and delete. "הצג בשרטוט" frames the line on the drawing (S11). Since S23b: current and breaking
 * capacity from a list (09 §7.4), a missing line's products ("מוצר אחר…", "אין כאן רכיב", 09 §7.8) and the bulk brand
 * discount on a line with no price (09 §7.13).
 */
export function LineDetail(props: {
  line: QuoteLine;
  findings: Finding[];
  onShowOnDrawing?: (line: QuoteLine) => void;
  actions?: DetailActions;
}) {
  const { line, findings, onShowOnDrawing, actions } = props;
  const own = lineFindings(line, findings);
  const editable = actions && !actions.locked ? actions : null;
  const derived = line.line_type === "derived" || line.line_type === "labor";
  const missing = line.line_type === "missing";
  const hasError = own.some((f) => f.severity === "error");
  const setAttribute = (attribute: string, value: string) =>
    editable &&
    value &&
    void editable.onAction(line, { kind: "attribute", attribute: attribute as EditableAttribute, value });
  return (
    <div className="detail" data-testid="line-detail" id={`detail-${line.line_id}`}>
      <div className="dgrid">
        <div style={{ display: "grid", gap: 8 }}>
          <span className="eyebrow">מה כתוב בשרטוט</span>
          {line.raw_text.length ? (
            <div className="raw">{line.raw_text.join("\n")}</div>
          ) : (
            <span className="small muted">אין טקסט בשרטוט לשורה הזו</span>
          )}
          {line.explanation && !missing ? <div className="small why">{line.explanation}</div> : null}
          {line.derived ? (
            <div className="small">
              <span className="muted">איך חושב: </span>
              {line.derived.explanation}
            </div>
          ) : null}
        </div>
        <div style={{ display: "grid", gap: 8, alignContent: "start" }}>
          <span className="eyebrow">מאיפה כל ערך</span>
          {line.sources.length ? (
            <dl className="kv">
              {line.sources.map((s) => {
                const src = sourceText(s);
                const options = editable ? line.attribute_options?.[s.attribute] : undefined; // an older API has none
                return (
                  <SourceRow
                    key={s.attribute}
                    label={attributeLabel(s.attribute)}
                    value={attributeValue(s.attribute, s.value)}
                    {...src}
                    options={options}
                    chosen={options ? attributeChoice(s.value, options) : ""}
                    unit={(v) => attributeValue(s.attribute, v) ?? v}
                    onChoose={(v) => setAttribute(s.attribute, v)}
                  />
                );
              })}
            </dl>
          ) : (
            <span className="small muted">אין תכונות שנקראו</span>
          )}
          {line.sku ? (
            <span className="small muted">
              מק"ט יצרן: <span className="mono">{line.sku}</span>
            </span>
          ) : null}
        </div>
      </div>
      {missing ? <MissingBox line={line} actions={editable} /> : null}
      {missing ? null : (
        <div className="dgrid">
          <div style={{ display: "grid", gap: 6, alignContent: "start" }}>
            <span className="eyebrow">מחיר</span>
            <PriceBox line={line} actions={editable} />
          </div>
          {line.included ? null : (
            <div style={{ display: "grid", gap: 6, alignContent: "start" }}>
              <span className="eyebrow">עלות ורווח</span>
              <CostBox line={line} actions={editable} floor={actions?.lineFloor ?? null} />
            </div>
          )}
        </div>
      )}
      {own.length ? (
        <div style={{ display: "grid", gap: 6 }}>
          <span className="eyebrow">ממצאי הבודק</span>
          {own.map((f) => (
            <div key={f.finding_id} style={{ display: "grid", gap: 6 }}>
              <div className="row small" style={{ alignItems: "stretch" }}>
                <span className={`sev ${f.severity}`} aria-hidden="true" />
                <span>
                  <b>{f.title ?? f.message}</b>
                  {f.title ? <span className="muted"> · {f.message}</span> : null}
                </span>
              </div>
              {editable && f.source !== "pricing" ? (
                <DismissControl finding={f} onDismiss={editable.onDismiss} />
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      {derived || missing ? null : (
        <div style={{ display: "grid", gap: 6 }}>
          <span className="eyebrow">חלופות</span>
          {line.alternatives.length ? (
            line.alternatives.slice(0, 3).map((alt, i) => (
              <div key={`${i}:${alt.description}`} className="alt">
                <span style={{ flex: 1 }}>{alt.description}</span>
                {editable ? (
                  <button
                    type="button"
                    className="btn sm"
                    data-testid="alt"
                    aria-keyshortcuts={String(i + 1)}
                    onClick={() => void editable.onAction(line, { kind: "alternative", index: i })}
                  >
                    החלף <span className="kbd">{i + 1}</span>
                  </button>
                ) : null}
              </div>
            ))
          ) : (
            <span className="small muted">אין חלופות. הדגם כתוב בשרטוט</span>
          )}
        </div>
      )}
      <div className="row">
        {onShowOnDrawing && line.boxes.length ? (
          <button type="button" className="btn sm" data-testid="showdraw" onClick={() => onShowOnDrawing(line)}>
            <Icon name="eye" />
            הצג בשרטוט
          </button>
        ) : null}
        {editable && line.qty_editable ? <QtyStepper line={line} actions={editable} /> : null}
        {editable && !line.approved && line.line_type !== "missing" && line.line_type !== "manual" ? (
          <button
            type="button"
            className="btn sm"
            data-testid="approve"
            onClick={() => void editable.onAction(line, { kind: "approve" })}
          >
            {hasError ? "אשר למרות הממצא" : "אשר שורה"}
          </button>
        ) : null}
        <span className="spacer" />
        {editable && !missing ? (
          <button
            type="button"
            className="btn ghost sm danger"
            data-testid="del"
            onClick={() => void editable.onAction(line, { kind: "delete" })}
          >
            {derived ? "הסר מההצעה" : "מחק שורה"}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function SourceRow(props: {
  label: string;
  value: string | null;
  text: string;
  warn: boolean;
  /** 09 §6.4: current and breaking capacity, from the catalog's values; choosing one matches the line again. */
  options?: string[] | undefined;
  chosen?: string;
  unit?: (v: string) => string;
  onChoose?: (v: string) => void;
}) {
  const id = useId();
  return (
    <>
      <dt>{props.options ? <label htmlFor={id}>{props.label}</label> : props.label}</dt>
      <dd>
        {props.options ? (
          <select
            id={id}
            className="input attr-sel"
            data-testid="attr"
            value={props.chosen ?? ""}
            onChange={(e) => props.onChoose?.(e.target.value)}
          >
            {props.chosen ? null : <option value="">{props.value ?? "—"}</option>}
            {props.options.map((v) => (
              <option key={v} value={v}>
                {props.unit ? props.unit(v) : v}
              </option>
            ))}
          </select>
        ) : (
          <b>{props.value ?? "—"}</b>
        )}
      </dd>
      <dd className={`small ${props.warn ? "warn-t" : "muted"}`}>{props.text}</dd>
    </>
  );
}

/**
 * 09 §6.4 "שורה חסרה": what was read beside the symbol the detection missed, up to three products by it (keys 1–3),
 * "מוצר אחר…" for the picker, and "אין כאן רכיב", which deletes the line.
 */
function MissingBox({ line, actions }: { line: QuoteLine; actions: DetailActions | null }) {
  const found = useQuery({
    queryKey: ["candidates", actions?.quoteId, line.line_id],
    queryFn: () => missingCandidates(actions?.quoteId ?? "", line.line_id),
    enabled: !!actions,
    staleTime: 60_000,
  });
  return (
    <div style={{ display: "grid", gap: 6 }} data-testid="missing">
      <span className="eyebrow">איזה רכיב זה?</span>
      <div className="small why">{missingText(line)}</div>
      {(found.data ?? []).map((c, i) => (
        <div key={c.ref} className="alt">
          <span style={{ flex: 1, display: "grid", gap: 2 }}>
            <span>{c.description}</span>
            <span className="small muted mono" dir="ltr">
              {choiceMeta(c)}
            </span>
          </span>
          <span className={`num${c.unit_price == null ? " small muted" : ""}`}>
            {c.unit_price == null ? "אין מחיר" : shekels(c.unit_price)}
          </span>
          {actions ? (
            <button
              type="button"
              className="btn sm"
              data-testid="candidate"
              aria-keyshortcuts={String(i + 1)}
              onClick={() => void actions.onAction(line, { kind: "resolve", ref: c.ref })}
            >
              בחר <span className="kbd">{i + 1}</span>
            </button>
          ) : null}
        </div>
      ))}
      {actions ? (
        <div className="row">
          <button
            type="button"
            className="btn sm"
            data-testid="other-product"
            onClick={() => actions.onPickProduct(line)}
          >
            מוצר אחר…
          </button>
          <span className="spacer" />
          <button
            type="button"
            className="btn ghost sm danger"
            data-testid="no-component"
            onClick={() => void actions.onAction(line, { kind: "delete" })}
          >
            אין כאן רכיב
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** 09 §7.13 "הזנה מרוכזת לפי מותג": every unpriced line of the brand, from its list price less the discount. */
function BrandBulk({ line, actions }: { line: QuoteLine; actions: DetailActions }) {
  const [pct, setPct] = useState("");
  const [bad, setBad] = useState(false);
  const id = useId();
  const save = async () => {
    const fraction = discountFraction(pct);
    setBad(fraction === null);
    if (fraction === null) return;
    if (await actions.onAction(line, { kind: "brand-discount", discount_pct: fraction })) setPct("");
  };
  return (
    <div className="row small brand-bulk" data-testid="brand-bulk">
      <label htmlFor={id}>כל המוצרים של {line.list_price_brand}: מחירון יצרן פחות</label>
      <input
        id={id}
        className={`input num${bad ? " err" : ""}`}
        style={{ width: 56, padding: "4px 8px", textAlign: "end" }}
        inputMode="decimal"
        value={pct}
        onChange={(e) => setPct(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void save();
        }}
      />
      <span>%</span>
      <button type="button" className="btn sm" data-testid="brand-save" onClick={() => void save()}>
        שמור
      </button>
    </div>
  );
}

const DISMISS_REASONS: [DismissReason, string][] = [
  ["intended", "מכוון"],
  ["checker_wrong", "הבודק טעה"],
  ["other", "אחר"],
];

/** 09 §6.4, §7.7: a reason from the list, then "דחה". "אחר" asks for a few words. */
export function DismissControl(props: {
  finding: Finding;
  onDismiss: (finding: Finding, reason: DismissReason, text?: string) => Promise<boolean>;
}) {
  const [reason, setReason] = useState<DismissReason>("intended");
  const [text, setText] = useState("");
  const id = useId();
  const missing = reason === "other" && !text.trim();
  return (
    <div className="row small" data-testid="dismiss">
      <label className="muted" htmlFor={id}>
        סיבת דחייה
      </label>
      <select
        id={id}
        className="input"
        style={{ width: "auto", padding: "4px 8px" }}
        value={reason}
        onChange={(e) => setReason(e.target.value as DismissReason)}
      >
        {DISMISS_REASONS.map(([k, label]) => (
          <option key={k} value={k}>
            {label}
          </option>
        ))}
      </select>
      {reason === "other" ? (
        <input
          className="input"
          style={{ width: 160, padding: "4px 8px" }}
          aria-label="למה הממצא לא נכון כאן"
          placeholder="למה?"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      ) : null}
      <button
        type="button"
        className="btn sm"
        disabled={missing}
        onClick={() => void props.onDismiss(props.finding, reason, reason === "other" ? text.trim() : undefined)}
      >
        דחה
      </button>
    </div>
  );
}

function QtyStepper({ line, actions }: { line: QuoteLine; actions: DetailActions }) {
  const n = Number(qtyText(line.qty));
  const set = (to: number) => void actions.onAction(line, { kind: "qty", qty: String(to) });
  return (
    <span className="qty-step" role="group" aria-label="כמות">
      <button type="button" className="btn sm" aria-label="הפחת כמות" disabled={n <= 1} onClick={() => set(n - 1)}>
        −
      </button>
      <b className="num" data-testid="qty">
        {qtyText(line.qty)}
      </b>
      <button type="button" className="btn sm" aria-label="הוסף כמות" onClick={() => set(n + 1)}>
        +
      </button>
    </span>
  );
}

function PriceBox({ line, actions }: { line: QuoteLine; actions: DetailActions | null }) {
  const [value, setValue] = useState(line.unit_price == null ? "" : qtyText(line.unit_price));
  const [pending, setPending] = useState<string | null>(null);
  const [bad, setBad] = useState(false);
  const inputId = useId();
  const titleId = useId();
  if (line.included) return <span className="small muted">כלול במחיר שורת האב (ערכה)</span>;
  if (line.unit_price == null)
    return (
      <>
        <span className="small">
          {line.price_hints.length
            ? `קרובים במחירון: ${line.price_hints.map((h) => `${h.name} ${shekels(h.unit_price)}`).join(", ")}`
            : "אין מחיר זהה במחירון. הקלידו מחיר בשורה"}
        </span>
        {actions ? (
          <label className="row small">
            <button
              type="button"
              className="toggle"
              role="switch"
              aria-checked={actions.saveToList}
              aria-label="שמור למחירון"
              data-testid="savelist"
              onClick={() => actions.onSaveToList(!actions.saveToList)}
            />
            שמור למחירון להצעות הבאות
          </label>
        ) : null}
        {actions && line.list_price_brand ? <BrandBulk line={line} actions={actions} /> : null}
      </>
    );
  const submit = () => {
    const amount = parseAmount(value);
    setBad(amount === null);
    if (amount === null || !actions) return;
    if (Number(amount) === Number(line.unit_price)) return;
    setPending(amount);
  };
  const choose = async (scope: "quote" | "catalog") => {
    if (!pending || !actions) return;
    const ok = await actions.onAction(line, { kind: "price", unit_price: pending, scope });
    if (ok) setPending(null);
  };
  return (
    <>
      <div className="row">
        <label className="small muted" htmlFor={inputId}>
          מחיר מכירה ליחידה
        </label>
        <input
          id={inputId}
          className={`input num${bad ? " err" : ""}`}
          style={{ width: 96, padding: "5px 8px", textAlign: "end" }}
          value={value}
          inputMode="decimal"
          disabled={!actions}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
        <button type="button" className="btn sm" data-testid="editprice" disabled={!actions} onClick={submit}>
          עדכן
        </button>
      </div>
      <span className="small muted">מקור: {line.override ? "שונה בהצעה הזו" : priceSourceText(line)}</span>
      {actions && line.fresh_price != null ? (
        <div className="row small fresh-box" data-testid="fresh">
          <span>
            במחירון יש מחיר חדש: <b className="num">{shekels(line.fresh_price)}</b>
          </span>
          <span className="spacer" />
          <button
            type="button"
            className="btn sm"
            data-testid="takefresh"
            onClick={() => void actions.onAction(line, { kind: "list-price" })}
          >
            עדכן בהצעה
          </button>
        </div>
      ) : null}
      {pending ? (
        <Modal onClose={() => setPending(null)} labelledBy={titleId}>
          <h2 id={titleId}>לעדכן גם במחירון?</h2>
          <span>
            שינית את המחיר של <b>{line.description}</b> מ-<b className="num">{shekels(line.unit_price)}</b> ל-
            <b className="num">{shekels(pending)}</b> בהצעה הזו.
          </span>
          <div className="small note-box">
            <span>
              <b>עדכון במחירון:</b> הצעות חדשות וחישוב מחדש ישתמשו במחיר החדש
              {line.price_source?.kind === "markup" || line.price_source?.kind === "margin" ? ", במקום חוק הרווח" : ""}.
            </span>
            <span>
              <b>הצעות שנשלחו לא משתנות.</b> טיוטות פתוחות לא משתנות לבד, ויציגו שיש מחיר חדש.
            </span>
          </div>
          <div className="row">
            {line.product_id ? (
              <button
                type="button"
                className="btn primary"
                data-testid="price-db"
                onClick={() => void choose("catalog")}
              >
                עדכן גם במחירון
              </button>
            ) : null}
            <button
              type="button"
              className={`btn${line.product_id ? "" : " primary"}`}
              data-testid="price-here"
              onClick={() => void choose("quote")}
            >
              רק בהצעה הזו
            </button>
            <span className="spacer" />
            <button type="button" className="btn ghost" onClick={() => setPending(null)}>
              ביטול
            </button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}

function CostBox({ line, actions, floor }: { line: QuoteLine; actions: DetailActions | null; floor: string | null }) {
  const [cost, setCost] = useState("");
  const [supplier, setSupplier] = useState("");
  const [bad, setBad] = useState(false);
  const selectId = useId();
  const chosen = line.suppliers.find((s) => s.chosen);
  const saveCost = async () => {
    const amount = parseAmount(cost);
    setBad(amount === null);
    if (amount === null || !actions) return;
    if (await actions.onAction(line, { kind: "cost", unit_cost: amount, supplier: supplier.trim() || null })) {
      setCost("");
      setSupplier("");
    }
  };
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {line.suppliers.length ? (
        <div className="row">
          <label className="small muted" htmlFor={selectId}>
            ספק
          </label>
          <select
            id={selectId}
            className="input"
            data-testid="supsel"
            style={{ width: "auto", padding: "5px 8px" }}
            value={chosen?.supplier_price_id ?? ""}
            disabled={!actions}
            onChange={(e) =>
              actions && void actions.onAction(line, { kind: "supplier", supplier_price_id: e.target.value })
            }
          >
            {chosen ? null : <option value="">—</option>}
            {line.suppliers.map((s) => (
              <option key={s.supplier_price_id} value={s.supplier_price_id}>
                {[
                  s.name ?? "ספק לא צוין",
                  shekels(s.unit_cost),
                  s.preferred ? "מועדף" : null,
                  s.lead_days != null ? `${s.lead_days} ימים` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {actions && line.supplier_id ? (
        <div className="row small">
          <span className="muted">הספק הוחלף רק בהצעה הזו.</span>
          <button
            type="button"
            className="btn ghost sm"
            data-testid="mkpref"
            onClick={() => void actions.onAction(line, { kind: "preferred" })}
          >
            הפוך למועדף במחירון
          </button>
        </div>
      ) : null}
      {line.unit_cost != null ? (
        <dl className="kv">
          <dt>עלות ליחידה</dt>
          <dd className="num">
            <b>{shekels(line.unit_cost)}</b>
          </dd>
          <dd className="small muted">{line.cost_source?.supplier ?? chosen?.name ?? ""}</dd>
          {line.unit_margin != null ? (
            <>
              <dt>רווח ליחידה</dt>
              <dd className="num">
                <b>{shekels(line.unit_margin)}</b>
              </dd>
              <dd className={`small ${line.below_floor ? "warn-t" : "muted"}`}>
                {percent(line.margin_pct)}
                {line.below_floor && floor ? ` · מתחת לרצפה (${percent(floor)})` : ""}
              </dd>
            </>
          ) : null}
        </dl>
      ) : (
        <>
          <span className="small muted">אין עלות למוצר הזה, ולכן אין חישוב רווח.</span>
          {actions ? (
            <div className="row">
              <input
                className={`input num${bad ? " err" : ""}`}
                aria-label="עלות ליחידה"
                placeholder="עלות"
                style={{ width: 84, padding: "5px 8px" }}
                inputMode="decimal"
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void saveCost();
                }}
              />
              <input
                className="input"
                aria-label="ספק"
                placeholder="ספק"
                style={{ width: 130, padding: "5px 8px" }}
                value={supplier}
                onChange={(e) => setSupplier(e.target.value)}
              />
              <button type="button" className="btn sm" data-testid="addcost" onClick={() => void saveCost()}>
                שמור עלות
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
