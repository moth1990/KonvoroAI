import { useQuery } from "@tanstack/react-query";
import { useDeferredValue, useId, useState } from "react";

import { searchProducts, type ProductChoice } from "../../api/client";
import { Modal } from "../../ui/Modal";
import { choiceMeta, shekels } from "./model";

/**
 * The product picker (09 §6.6 step 3, §6.4 "מוצר אחר…"; S23b, no prototype screen): a free search over the master
 * catalog and the factory's price list, by description, SKU or maker, the line's family first when it has one.
 * Priced products come first, each with its price or "אין מחיר" (S23b decision 2). ↑ / ↓ move, Enter picks.
 */
export function ProductPicker(props: {
  quoteId: string;
  title: string;
  /** The line's family: the list starts with it; clearing the search box widens to every family. */
  family?: string | null;
  onPick: (choice: ProductChoice) => void;
  onClose: () => void;
}) {
  const { quoteId, family } = props;
  const [q, setQ] = useState("");
  const [only, setOnly] = useState(!!family);
  const [active, setActive] = useState(0);
  const query = useDeferredValue(q.trim());
  const titleId = useId();
  const listId = useId();
  const found = useQuery({
    queryKey: ["products", quoteId, query, only ? family : null],
    queryFn: () => searchProducts(quoteId, query, only ? family : null),
    staleTime: 30_000,
  });
  const items = found.data ?? [];
  const at = Math.min(active, Math.max(0, items.length - 1));
  const pick = (c: ProductChoice | undefined) => c && props.onPick(c);

  return (
    <Modal onClose={props.onClose} labelledBy={titleId} className="picker">
      <h2 id={titleId}>{props.title}</h2>
      <input
        className="input"
        role="combobox"
        aria-expanded="true"
        aria-controls={listId}
        aria-activedescendant={items[at] ? `${listId}-${at}` : undefined}
        aria-label="חיפוש מוצר"
        placeholder='תיאור, מק"ט או יצרן'
        data-testid="picker-search"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setActive(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setActive((i) => Math.min(items.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1))));
          } else if (e.key === "Enter") {
            e.preventDefault();
            pick(items[at]);
          }
        }}
      />
      {family ? (
        <label className="row small">
          <input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} />
          רק מאותה משפחה
        </label>
      ) : null}
      <div className="picker-list" role="listbox" id={listId} aria-label="מוצרים" data-testid="picker-list">
        {found.isPending ? <span className="small muted">מחפש…</span> : null}
        {!found.isPending && items.length === 0 ? (
          <span className="small muted">לא נמצא מוצר. נסו מילה אחרת או מק"ט</span>
        ) : null}
        {items.map((c, i) => (
          <div
            key={c.ref}
            id={`${listId}-${i}`}
            role="option"
            aria-selected={i === at}
            className="pick"
            data-testid="pick"
            onMouseEnter={() => setActive(i)}
            onClick={() => pick(c)}
          >
            <span style={{ display: "grid", gap: 2, minWidth: 0 }}>
              <b>{c.description}</b>
              <span className="small muted mono" dir="ltr">
                {choiceMeta(c)}
              </span>
            </span>
            <span className={`num${c.unit_price == null ? " small muted" : ""}`}>
              {c.unit_price == null ? "אין מחיר" : shekels(c.unit_price)}
            </span>
          </div>
        ))}
      </div>
      <div className="row">
        <span className="small muted">
          <span className="kbd">↑</span> <span className="kbd">↓</span> בחירה · <span className="kbd">Enter</span> הוספה
        </span>
        <span className="spacer" />
        <button type="button" className="btn ghost" onClick={props.onClose}>
          ביטול
        </button>
      </div>
    </Modal>
  );
}
