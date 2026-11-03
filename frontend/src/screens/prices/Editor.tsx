import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, checkCost, fetchProduct, fetchSuppliers } from "../../api/client";
import { useMe } from "../../api/QueryProvider";
import { Icon } from "../../ui/Icon";
import { Modal } from "../../ui/Modal";
import { useToast } from "../../ui/Toast";
import {
  blankRow,
  dayMonth,
  draftOf,
  draftsText,
  ENCLOSURE,
  FAMILIES,
  familyLabel,
  historyText,
  INCLUDES,
  isError,
  moneyIn,
  PRODUCTS_KEY,
  savedText,
  toBody,
  typedHere,
  UNITS,
  warningText,
  type Draft,
  type DraftError,
  type DraftRow,
  type Product,
  type ProductBody,
  type SanityWarning,
} from "./model";

const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";

/** Today in the tenant's timezone, as the API's date: a cost typed now is dated now (07 §7.2.2 `price_date`). */
function todayIn(timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, dateStyle: "short" }).format(new Date());
}

/**
 * The product editor (prototype `openEditor` / `saveEditor`, lines 1147–1208; 07 §7.2.1): the record, its suppliers
 * with one preferred, a fixed price or the margin rule, "כלול בארון" for a cabinet (S19 decision 2), consumable, the
 * drafts that use it, and its history. A cost typed here is checked on blur (10 §8, S19 decision 4).
 */
export function ProductEditor({
  product,
  ruleText,
  includesDefault,
  onClose,
  save,
}: {
  product: Product | null;
  ruleText: string | null;
  includesDefault: Record<string, boolean>;
  onClose: () => void;
  save: (id: string | null, body: ProductBody) => Promise<Product>;
}) {
  const me = useMe();
  const queries = useQueryClient();
  const toast = useToast();
  const tz = me.data?.tenant.timezone ?? "Asia/Jerusalem";
  // the list row has no history or drafts: the product's own GET has them
  const full = useQuery({
    queryKey: ["price-list", "product", product?.id],
    queryFn: () => fetchProduct(product?.id ?? ""),
    enabled: product !== null,
  });
  const suppliers = useQuery({ queryKey: ["price-list", "suppliers"], queryFn: () => fetchSuppliers() });
  const [d, setD] = useState<Draft>(() => draftOf(product, includesDefault));
  const [error, setError] = useState<DraftError | null>(null);
  const [warnings, setWarnings] = useState<Record<string, SanityWarning[]>>({});
  const [saving, setSaving] = useState(false);
  const shown = full.data ?? product;
  const names = new Map((suppliers.data ?? []).map((s) => [s.id, s.name]));

  const set = (patch: Partial<Draft>) => {
    setD((x) => ({ ...x, ...patch }));
    setError(null);
  };
  const setRow = (key: string, patch: Partial<DraftRow>) => {
    setD((x) => ({ ...x, rows: x.rows.map((r) => (r.key === key ? { ...r, ...patch } : r)) }));
    setError(null);
  };

  async function check(r: DraftRow) {
    const cost = moneyIn(r.cost);
    if (cost === null || !typedHere(r) || (!product && !d.family)) {
      setWarnings((w) => ({ ...w, [r.key]: [] }));
      return;
    }
    try {
      const result = await checkCost({
        unit_cost: cost,
        currency: r.saved?.currency ?? "ILS",
        product_id: product?.id ?? null,
        row_id: r.id ?? null,
        family: d.family || null,
        brand: d.brand.trim() || null,
      });
      setWarnings((w) => ({ ...w, [r.key]: result.warnings }));
    } catch {
      setWarnings((w) => ({ ...w, [r.key]: [] })); // a check that fails never stops the user
    }
  }

  async function submit() {
    const out = toBody(d, todayIn(tz));
    if (isError(out)) {
      setError(out);
      toast(out.message);
      return;
    }
    setSaving(true);
    try {
      const saved = await save(product?.id ?? null, out.body);
      queries.setQueryData<Product[]>(PRODUCTS_KEY, (list) =>
        list ? (product ? list.map((x) => (x.id === saved.id ? saved : x)) : [saved, ...list]) : list,
      );
      void queries.invalidateQueries({ queryKey: ["price-list"] });
      toast(savedText(product, saved));
      onClose();
    } catch (err) {
      setSaving(false);
      toast(err instanceof ApiError ? err.message : FALLBACK);
    }
  }

  const preferredOf = d.rows.findIndex((r) => r.preferred);
  const drafts = shown ? draftsText(shown) : null;
  const history = shown?.history ?? [];
  const familyKnown = FAMILIES.some(([code]) => code === d.family);

  return (
    <Modal onClose={onClose} labelledBy="ed-h" className="wide">
      <div className="row">
        <h2 id="ed-h" style={{ flex: 1 }}>
          {product ? "עריכת מוצר" : "מוצר חדש"}
        </h2>
        <button type="button" className="btn ghost sm" aria-label="סגור" onClick={onClose}>
          <Icon name="x" />
        </button>
      </div>
      <div className="form2">
        <div className="field" style={{ gridColumn: "1/-1" }}>
          <label htmlFor="ed-p">שם המוצר בהצעה</label>
          <input
            className={`input ${error?.field === "name" ? "err" : ""}`.trim()}
            id="ed-p"
            value={d.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="ed-sku">מק"ט יצרן</label>
          <input
            className="input mono"
            id="ed-sku"
            dir="ltr"
            value={d.sku}
            onChange={(e) => set({ sku: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="ed-brand">יצרן</label>
          <input className="input" id="ed-brand" value={d.brand} onChange={(e) => set({ brand: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="ed-fam">משפחה</label>
          <select
            className={`input ${error?.field === "family" ? "err" : ""}`.trim()}
            id="ed-fam"
            value={d.family}
            onChange={(e) => {
              const family = e.target.value;
              set({ family, includes: family === ENCLOSURE ? (d.includes ?? { ...includesDefault }) : d.includes });
            }}
          >
            <option value="" disabled>
              בחרו משפחה
            </option>
            {!familyKnown && d.family ? <option value={d.family}>{familyLabel(d.family)}</option> : null}
            {FAMILIES.map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="ed-unit">יחידה</label>
          <select className="input" id="ed-unit" value={d.unit} onChange={(e) => set({ unit: e.target.value })}>
            {UNITS.some(([code]) => code === d.unit) ? null : <option value={d.unit}>{d.unit}</option>}
            {UNITS.map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div style={{ display: "grid", gap: 6 }}>
        <span className="eyebrow">ספקים ועלות</span>
        <div className="tbl-wrap">
          <table className="tbl sup-tbl">
            <thead>
              <tr>
                <th>מועדף</th>
                <th>ספק</th>
                <th>מק"ט ספק</th>
                <th>עלות</th>
                <th>ימי אספקה</th>
                <th />
              </tr>
            </thead>
            <tbody id="ed-sups">
              {d.rows.map((r, i) => (
                <SupplierRowEdit
                  key={r.key}
                  r={r}
                  i={i}
                  preferred={preferredOf === i}
                  bad={error?.field === "rows" && error.row === r.key}
                  warnings={warnings[r.key] ?? []}
                  onChange={(patch) => setRow(r.key, patch)}
                  onPrefer={() =>
                    setD((x) => ({ ...x, rows: x.rows.map((y) => ({ ...y, preferred: y.key === r.key })) }))
                  }
                  onBlurCost={() => void check(r)}
                  onRemove={() => {
                    setD((x) => ({ ...x, rows: x.rows.filter((y) => y.key !== r.key) }));
                    setWarnings((w) => ({ ...w, [r.key]: [] }));
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
        <div className="row">
          <button
            type="button"
            className="btn sm"
            data-testid="ed-addsup"
            onClick={() => setD((x) => ({ ...x, rows: [...x.rows, blankRow()] }))}
          >
            <Icon name="plus" />
            הוסף ספק
          </button>
          <span className="small muted">בלי מועדף, העלות בהצעה היא של הזול ביותר</span>
        </div>
      </div>

      <div style={{ display: "grid", gap: 6 }}>
        <span className="eyebrow">מחיר מכירה</span>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <label className="row small">
            <input
              type="radio"
              name="ed-mode"
              value="fixed"
              checked={d.mode === "fixed"}
              onChange={() => set({ mode: "fixed" })}
            />{" "}
            מחיר קבוע
          </label>
          <input
            className={`input num ${error?.field === "sale" ? "err" : ""}`.trim()}
            id="ed-sale"
            inputMode="decimal"
            style={{ width: 100 }}
            aria-label="מחיר מכירה"
            value={d.sale}
            onChange={(e) => set({ sale: e.target.value })}
          />
          <label className="row small">
            <input
              type="radio"
              name="ed-mode"
              value="rule"
              checked={d.mode === "rule"}
              onChange={() => set({ mode: "rule" })}
            />{" "}
            לפי חוק הרווח{ruleText ? ` (${ruleText} על עלות הספק המועדף)` : ""}
          </label>
        </div>
        {d.mode === "rule" && !d.rows.some((r) => moneyIn(r.cost) !== null) ? (
          <span className="small warn-msg" data-testid="ed-nocost">
            בלי ספק אין עלות, ולכן אין מחיר
          </span>
        ) : null}
      </div>

      {d.family === ENCLOSURE && d.includes ? (
        <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend style={{ fontWeight: 500, fontSize: 13, padding: 0, marginBottom: 5 }}>כלול בארון</legend>
          <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
            {INCLUDES.map(([key, label]) => (
              <label key={key} className="row small">
                <input
                  type="checkbox"
                  checked={d.includes?.[key] === true}
                  onChange={(e) => set({ includes: { ...(d.includes ?? {}), [key]: e.target.checked } })}
                />{" "}
                {label}
              </label>
            ))}
          </div>
          <span className="small muted">מה שמסומן כאן לא יתומחר פעמיים בהצעה</span>
        </fieldset>
      ) : null}

      <label className="row small">
        <input
          type="checkbox"
          id="ed-cons"
          checked={d.consumable}
          onChange={(e) => set({ consumable: e.target.checked })}
        />{" "}
        חומר עזר: לא שורה נפרדת בהצעה, והבודק לא מסמן אותו כהשמטה
      </label>

      {drafts ? (
        <div
          className="small"
          data-testid="ed-drafts"
          style={{ background: "var(--surface-2)", padding: 10, borderRadius: "var(--r-sm)" }}
        >
          {drafts}. שינוי מחיר יוצג שם כ"מחיר חדש במחירון", ויעודכן רק כשתאשרו. <b>הצעות שנשלחו לא משתנות.</b>
        </div>
      ) : null}

      {history.length ? (
        <details data-testid="ed-history">
          <summary className="small" style={{ cursor: "pointer" }}>
            היסטוריה ({history.length})
          </summary>
          <div style={{ display: "grid", gap: 4, marginTop: 6 }}>
            {history.map((h) => (
              <span key={h.id} className="small">
                <span className="muted num">{dayMonth(h.changed_at, tz)}</span> · {historyText(h, names)}
              </span>
            ))}
          </div>
        </details>
      ) : null}

      <div className="row">
        <button
          type="button"
          className="btn primary"
          data-testid="ed-save"
          disabled={saving}
          onClick={() => void submit()}
        >
          שמור
        </button>
        <button type="button" className="btn ghost" onClick={onClose}>
          ביטול
        </button>
      </div>
    </Modal>
  );
}

function SupplierRowEdit({
  r,
  i,
  preferred,
  bad,
  warnings,
  onChange,
  onPrefer,
  onBlurCost,
  onRemove,
}: {
  r: DraftRow;
  i: number;
  preferred: boolean;
  bad: boolean;
  warnings: SanityWarning[];
  onChange: (patch: Partial<DraftRow>) => void;
  onPrefer: () => void;
  onBlurCost: () => void;
  onRemove: () => void;
}) {
  const label = r.name.trim() || `שורה ${i + 1}`;
  return (
    <>
      <tr data-sup={i} data-testid="sup-row">
        <td>
          <input
            type="radio"
            name="ed-pref"
            checked={preferred}
            onChange={onPrefer}
            aria-label={`ספק מועדף: ${label}`}
          />
        </td>
        <td>
          <input
            className="input"
            placeholder="שם הספק"
            aria-label="שם הספק"
            style={{ minWidth: 120 }}
            value={r.name}
            onChange={(e) => onChange({ name: e.target.value })}
          />
        </td>
        <td>
          <input
            className="input"
            placeholder='מק"ט ספק'
            aria-label='מק"ט ספק'
            style={{ width: 100 }}
            value={r.supplierSku}
            onChange={(e) => onChange({ supplierSku: e.target.value })}
          />
        </td>
        <td>
          <input
            className={`input num ${bad ? "err" : ""}`.trim()}
            inputMode="decimal"
            aria-label={`עלות: ${label}`}
            style={{ width: 80 }}
            value={r.cost}
            onChange={(e) => onChange({ cost: e.target.value })}
            onBlur={onBlurCost}
          />
        </td>
        <td>
          <input
            className="input num"
            inputMode="numeric"
            aria-label={`ימי אספקה: ${label}`}
            style={{ width: 56 }}
            value={r.lead}
            onChange={(e) => onChange({ lead: e.target.value })}
          />
        </td>
        <td>
          <button type="button" className="btn ghost sm" data-testid="ed-rmsup" aria-label="הסר ספק" onClick={onRemove}>
            <Icon name="x" />
          </button>
        </td>
      </tr>
      {warnings.length ? (
        <tr data-testid="sanity">
          <td colSpan={6} className="small warn-t" role="status">
            {warnings.map((w) => (
              <div key={w.code}>{warningText(w)}</div>
            ))}
          </td>
        </tr>
      ) : null}
    </>
  );
}
