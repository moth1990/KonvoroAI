import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  ApiError,
  deleteLogo,
  fetchDocumentSettings,
  saveDocumentSettings,
  uploadLogo,
  type DocumentSettings,
} from "../../api/client";
import { Icon } from "../../ui/Icon";
import { useToast } from "../../ui/Toast";
import { documentBody, documentForm, sameForm, type DocumentForm } from "./model";

const KEY = ["document-settings"];
const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";

/**
 * "המסמך ללקוח" (13 §4.1 "לוגו, פרטים, תנאים", §6 item 2; S26 decision 1), behind `export_doc`. The prototype has
 * no such section, so it is the settings screen's own classes: the logo, the factory's details and terms as the
 * customer PDF prints them, and whether SKUs show (07 §12). The details and terms save with "שמור"; the logo at once.
 */
export function DocumentSection() {
  const toast = useToast();
  const queries = useQueryClient();
  const settings = useQuery({ queryKey: KEY, queryFn: () => fetchDocumentSettings() });
  const [form, setForm] = useState<DocumentForm | null>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const s = settings.data;
  const shown = form ?? (s ? documentForm(s) : null);
  const dirty = !!(form && s && !sameForm(form, documentForm(s)));
  const edit = (patch: Partial<DocumentForm>) => shown && setForm({ ...shown, ...patch });

  async function run(call: () => Promise<DocumentSettings>, message: string, after?: () => void) {
    setBusy(true);
    try {
      queries.setQueryData(KEY, await call());
      after?.();
      toast(message);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : FALLBACK);
    } finally {
      setBusy(false);
    }
  }

  const field = (key: keyof Omit<DocumentForm, "terms" | "show_sku">, label: string, dir?: "ltr") => (
    <div className="field">
      <label htmlFor={`doc-${key}`}>{label}</label>
      <input
        className="input"
        id={`doc-${key}`}
        dir={dir}
        value={shown?.[key] ?? ""}
        disabled={!shown}
        autoComplete="off"
        onChange={(e) => edit({ [key]: e.target.value })}
      />
    </div>
  );

  return (
    <section className="card set-sec" data-testid="document-settings">
      <div className="sec-head">
        <h2>המסמך ללקוח</h2>
        <span className="v2">דגל</span>
        <span className="small muted">מה שמודפס ב-PDF ללקוח, מעל השורות ומתחת לסיכום</span>
      </div>
      <div className="set-row">
        <div>
          <b>לוגו</b>
          <br />
          <span className="small muted">PNG או JPEG, עד 1MB. מודפס בראש המסמך</span>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {s?.logo_url ? (
            <img className="doc-logo" src={s.logo_url} alt="הלוגו של המפעל" data-testid="doc-logo" />
          ) : null}
          <input
            ref={file}
            type="file"
            accept="image/png,image/jpeg"
            hidden
            data-testid="doc-logo-file"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void run(() => uploadLogo(f), "הלוגו נשמר");
            }}
          />
          <button type="button" className="btn sm" disabled={!s || busy} onClick={() => file.current?.click()}>
            <Icon name="upload" />
            {s?.logo_url ? "החלפה" : "העלאה"}
          </button>
          {s?.logo_url ? (
            <button
              type="button"
              className="btn ghost sm"
              disabled={busy}
              onClick={() => void run(deleteLogo, "הלוגו הוסר")}
            >
              הסרה
            </button>
          ) : null}
        </div>
      </div>
      <div className="set-row" style={{ gridTemplateColumns: "1fr" }}>
        <div className="form2">
          {field("name", "שם המפעל")}
          {field("company_id", "ח.פ.", "ltr")}
          {field("address", "כתובת")}
          {field("phone", "טלפון", "ltr")}
        </div>
        <div className="field">
          <label htmlFor="doc-terms">תנאים</label>
          <textarea
            className="input"
            id="doc-terms"
            rows={4}
            value={shown?.terms ?? ""}
            disabled={!shown}
            placeholder="למשל: ההצעה בתוקף 30 יום. תנאי תשלום: שוטף + 60"
            onChange={(e) => edit({ terms: e.target.value })}
          />
        </div>
      </div>
      <div className="set-row">
        <div>
          <b>הצג מק"ט במסמך</b>
          <br />
          <span className="small muted">עמודת מק"ט ליד התיאור. בלי עלות, ספק או רווח בכל מקרה</span>
        </div>
        <button
          type="button"
          className="toggle"
          role="switch"
          aria-checked={!!shown?.show_sku}
          aria-label='הצג מק"ט במסמך'
          disabled={!shown}
          data-testid="doc-sku"
          onClick={() => edit({ show_sku: !shown?.show_sku })}
        />
      </div>
      <div className="set-row">
        <span className="small muted">{dirty ? "יש שינויים שלא נשמרו" : ""}</span>
        <button
          type="button"
          className={`btn sm${dirty ? " primary" : ""}`}
          disabled={!dirty || busy || !shown?.name.trim()}
          data-testid="doc-save"
          onClick={() =>
            shown &&
            void run(
              () => saveDocumentSettings(documentBody(shown)),
              "המסמך ללקוח עודכן",
              () => setForm(null),
            )
          }
        >
          שמור
        </button>
      </div>
    </section>
  );
}
