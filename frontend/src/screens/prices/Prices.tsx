import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  createProduct,
  deleteBrandDiscount,
  fetchBrandDiscounts,
  fetchBrands,
  fetchMarginRules,
  fetchProducts,
  fetchSettings,
  setBrandDiscount,
  updateProduct,
} from "../../api/client";
import { useMe } from "../../api/QueryProvider";
import { Shell } from "../../shell/Shell";
import { Icon } from "../../ui/Icon";
import { useToast } from "../../ui/Toast";
import { ProductEditor } from "./Editor";
import {
  costSupplier,
  dayMonth,
  familyLabel,
  FILTERS,
  percent,
  percentToRate,
  PRODUCTS_KEY,
  ratePercent,
  rateToPercent,
  saleModeText,
  shekels,
  sourceText,
  stats,
  supplierShort,
  visible,
  type Filter,
  type Product,
} from "./model";

const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";

/** The price list (07 §7.2, prototype `vPrices`, lines 1098–1146): four cards, the table with its search and chips,
 * the note on several suppliers, and the bulk brand discount. The editor is `ProductEditor`. */
export function PricesScreen() {
  const me = useMe();
  const queries = useQueryClient();
  const toast = useToast();
  const products = useQuery({ queryKey: PRODUCTS_KEY, queryFn: () => fetchProducts() });
  const rules = useQuery({ queryKey: ["price-list", "margin-rules"], queryFn: () => fetchMarginRules() });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => fetchSettings() });
  const [q, setQ] = useState("");
  const [f, setF] = useState<Filter>("all");
  // null: closed; "new": a new product; otherwise the product being edited
  const [editing, setEditing] = useState<Product | "new" | null>(null);

  const all = products.data ?? [];
  const rows = visible(all, q, f);
  const s = stats(all);
  const rule = rules.data?.find((r) => r.level === "default" && !r.customer_id);
  const floor = settings.data?.min_line_margin;
  const tz = me.data?.tenant.timezone ?? "Asia/Jerusalem";

  async function toggleConsumable(p: Product) {
    try {
      const saved = await updateProduct(p.id, { consumable: !p.consumable });
      queries.setQueryData<Product[]>(PRODUCTS_KEY, (list) => list?.map((x) => (x.id === saved.id ? saved : x)));
      toast(saved.consumable ? "סומן כחומר עזר: לא שורה נפרדת בהצעה" : "בוטל סימון חומר עזר");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
    }
  }

  return (
    <Shell title="מחירון">
      <div className="stats four">
        <div className="card stat">
          <span className="eyebrow">מוצרים במחירון</span>
          <b className="num" data-testid="stat-count">
            {s.count}
          </b>
          <span className="small muted">{s.multi} עם יותר מספק אחד</span>
        </div>
        <div className="card stat">
          <span className="eyebrow">רווח ממוצע</span>
          <b className="num">{s.avgMargin}</b>
          <span className="small muted">מחיר מכירה מול עלות הספק המועדף</span>
        </div>
        <div className="card stat">
          <span className="eyebrow">בלי עלות</span>
          <b className="num" data-testid="stat-nocost">
            {s.noCost}
          </b>
          <span className="small muted">אין ספק, ולכן אין חישוב רווח</span>
        </div>
        <div className="card stat">
          <span className="eyebrow">חוק רווח</span>
          <b className="num">{rule?.value ? ratePercent(rule.value) : "—"}</b>
          <span className="small muted">
            {rule?.kind === "margin" ? "רווח מהמחיר" : "תוספת על העלות"} · רצפה {floor ? ratePercent(floor) : "—"}
          </span>
        </div>
      </div>

      <section className="card">
        <div className="sec-head" style={{ flexWrap: "wrap" }}>
          <h2>המחירון</h2>
          <span className="spacer" />
          <input
            className="input"
            id="price-q"
            type="search"
            placeholder='חיפוש: מוצר, מק"ט, ספק'
            aria-label='חיפוש: מוצר, מק"ט, ספק'
            style={{ maxWidth: 240, padding: "6px 10px" }}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button type="button" className="btn primary sm" data-testid="prod-new" onClick={() => setEditing("new")}>
            <Icon name="plus" />
            הוסף מוצר
          </button>
        </div>
        <div className="row" style={{ padding: "10px 16px", gap: 6, borderBottom: "1px solid var(--line)" }}>
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              className="fchip"
              data-testid={`pricef-${key}`}
              aria-pressed={f === key}
              onClick={() => setF(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="tbl-wrap">
          <table className="tbl" data-testid="price-table">
            <thead>
              <tr>
                <th>מוצר</th>
                <th>ספקים</th>
                <th>עלות</th>
                <th>מכירה</th>
                <th>רווח</th>
                <th>מקור</th>
                <th>חומר עזר</th>
              </tr>
            </thead>
            <tbody>
              {products.isError ? (
                <tr>
                  <td colSpan={7} className="err-msg" role="alert">
                    לא הצלחנו לטעון את המחירון. נסו לרענן את הדף
                  </td>
                </tr>
              ) : null}
              {rows.map((p) => (
                <ProductRow
                  key={p.id}
                  p={p}
                  tz={tz}
                  onOpen={() => setEditing(p)}
                  onConsumable={() => void toggleConsumable(p)}
                />
              ))}
              {products.data && !rows.length ? (
                <tr>
                  <td colSpan={7} className="muted">
                    אין מוצרים שמתאימים לחיפוש
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card pad" style={{ display: "grid", gap: 8 }}>
        <h2>כשלאותו מוצר יש כמה ספקים</h2>
        <span className="small muted">
          כל מוצר שומר את כל הספקים שלו, עם עלות, זמן אספקה ומק"ט ספק. העלות בהצעה נלקחת מהספק המועדף, ואם אין מועדף,
          מהזול ביותר. בכל שורה בהצעה אפשר לבחור ספק אחר, רק להצעה הזו. מחיר המכירה לא משתנה כשמחליפים ספק, רק הרווח.
        </span>
      </section>

      <BrandDiscountForm />

      {editing ? (
        <ProductEditor
          product={editing === "new" ? null : editing}
          ruleText={rule?.value ? ratePercent(rule.value) : null}
          includesDefault={settings.data?.enclosure_includes_default ?? {}}
          onClose={() => setEditing(null)}
          save={(id, body) => (id ? updateProduct(id, body) : createProduct({ ...body, source: "manual_entry" }))}
        />
      ) : null}
    </Shell>
  );
}

function ProductRow({
  p,
  tz,
  onOpen,
  onConsumable,
}: {
  p: Product;
  tz: string;
  onOpen: () => void;
  onConsumable: () => void;
}) {
  const sup = costSupplier(p);
  return (
    <tr
      className="click"
      data-testid="prod"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onOpen();
        }
      }}
    >
      <td>
        <div className="prod-cell">
          <b>{p.display_name}</b>
          <span className="small muted">
            {p.manufacturer_sku ? (
              <>
                <span className="mono" dir="ltr">
                  {p.manufacturer_sku}
                </span>
                {" · "}
              </>
            ) : null}
            {p.brand ?? "—"} · {familyLabel(p.family)}
          </span>
        </div>
      </td>
      <td>
        {sup ? (
          <>
            <span className="small">{supplierShort(sup)}</span>
            {p.suppliers.length > 1 ? <span className="chip acc">+{p.suppliers.length - 1}</span> : null}
          </>
        ) : (
          <span className="chip bad">אין ספק</span>
        )}
      </td>
      <td className="n">
        {p.unit_cost ? <span className="num">{shekels(p.unit_cost)}</span> : <span className="muted">—</span>}
      </td>
      <td className="n">
        {p.unit_price ? <span className="num">{shekels(p.unit_price)}</span> : <span className="muted">—</span>}
        <br />
        <span className="small muted">{saleModeText(p)}</span>
      </td>
      <td className={`n ${p.below_margin_floor ? "warn-t" : ""}`.trim()}>
        {p.margin_pct ? <span className="num">{percent(p.margin_pct)}</span> : <span className="muted">—</span>}
      </td>
      <td className="small muted">
        {sourceText(p)}
        <br />
        <span className="num">{p.last_changed_at ? dayMonth(p.last_changed_at, tz) : ""}</span>
      </td>
      <td onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
        <button
          type="button"
          className="toggle"
          role="switch"
          aria-checked={p.consumable}
          data-testid="cons"
          aria-label={`חומר עזר: ${p.display_name}`}
          onClick={onConsumable}
        />
      </td>
    </tr>
  );
}

/** "הנחת מותג גורפת" (07 §7.2, priority 2): for products with no price, the brand's list price less the discount.
 * The brand's saved discount fills the field; saving an empty field removes it. */
function BrandDiscountForm() {
  const queries = useQueryClient();
  const toast = useToast();
  const brands = useQuery({ queryKey: ["price-list", "brands"], queryFn: () => fetchBrands() });
  const discounts = useQuery({ queryKey: ["price-list", "brand-discounts"], queryFn: () => fetchBrandDiscounts() });
  const [brand, setBrand] = useState<string | null>(null);
  const [typed, setTyped] = useState<string | null>(null);
  const [bad, setBad] = useState(false);
  const chosen = brand ?? brands.data?.[0] ?? "";
  const saved = discounts.data?.find((d) => d.brand === chosen);
  const pct = typed ?? (saved ? rateToPercent(saved.discount_pct) : "");

  async function save() {
    const rate = pct.trim() ? percentToRate(pct) : null;
    if (pct.trim() && rate === null) {
      setBad(true);
      toast("הנחה באחוזים, בין 0 ל-100");
      return;
    }
    try {
      if (rate) {
        await setBrandDiscount(chosen, rate);
        toast(`נשמר: ${chosen}, הנחה ${rateToPercent(rate)}% ממחירון היצרן`);
      } else if (saved) {
        await deleteBrandDiscount(chosen);
        toast(`הוסרה ההנחה של ${chosen}`);
      } else {
        setBad(true);
        toast("הזינו הנחה באחוזים");
        return;
      }
      setTyped(null);
      void queries.invalidateQueries({ queryKey: ["price-list"] });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
    }
  }

  return (
    <section className="card pad" style={{ display: "grid", gap: 12 }}>
      <h2>הנחת מותג גורפת</h2>
      <span className="muted">למוצרים בלי מחיר: מחירון היצרן פחות ההנחה שלך. השורות יוצאות צהובות עד שתאשר.</span>
      <div className="row" style={{ alignItems: "end" }}>
        <div className="field" style={{ minWidth: 160 }}>
          <label htmlFor="brand">מותג</label>
          <select
            className="input"
            id="brand"
            value={chosen}
            onChange={(e) => {
              setBrand(e.target.value);
              setTyped(null);
              setBad(false);
            }}
          >
            {(brands.data ?? []).map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ width: 120 }}>
          <label htmlFor="disc">הנחה (%)</label>
          <input
            className={`input num ${bad ? "err" : ""}`.trim()}
            id="disc"
            inputMode="decimal"
            value={pct}
            onChange={(e) => {
              setTyped(e.target.value);
              setBad(false);
            }}
          />
        </div>
        <button
          type="button"
          className="btn primary"
          data-testid="brand-save"
          disabled={!chosen}
          onClick={() => void save()}
        >
          שמור
        </button>
      </div>
      {saved ? (
        <span className="small muted" data-testid="brand-priced">
          {saved.priced_products === 1
            ? "מוצר אחד מתומחר היום מההנחה הזו"
            : `${saved.priced_products} מוצרים מתומחרים היום מההנחה הזו`}
        </span>
      ) : null}
    </section>
  );
}
