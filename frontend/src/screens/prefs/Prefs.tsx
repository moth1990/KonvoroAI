import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { ApiError, fetchSettings, patchSettings, type SettingsPatch, type TenantSettings } from "../../api/client";
import { useMe } from "../../api/QueryProvider";
import { quotaView } from "../../shell/quota";
import { Shell, useSignOut } from "../../shell/Shell";
import { Icon } from "../../ui/Icon";
import { useToast } from "../../ui/Toast";
import { MAX_FILE_MB } from "../newQuote/model";
import { markupRate, ratePercentText } from "../welcome/model";
import { BRAND_ROWS, BRANDS, FLAG_ROWS, INCLUDES, rcd30, withRcd30, type EnclosurePart } from "./model";

const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";
const SETTINGS_KEY = ["settings"];

function Toggle({
  label,
  on,
  onChange,
  disabled = false,
  testId,
}: {
  label: string;
  on: boolean;
  onChange?: () => void;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <button
      type="button"
      className="toggle"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      data-testid={testId}
      onClick={onChange}
    />
  );
}

function Row({ title, sub, children }: { title: React.ReactNode; sub?: string; children: React.ReactNode }) {
  return (
    <div className="set-row">
      <div>
        <b>{title}</b>
        {sub ? (
          <>
            <br />
            <span className="small muted">{sub}</span>
          </>
        ) : null}
      </div>
      {children}
    </div>
  );
}

/**
 * The settings screen (prototype `vPrefs`, lines 1228–1251): the plan and its limits, pricing, what the enclosure's
 * price includes, defaults, the flags and the account. Two brand selects, breakers and RCDs (S24 decision 2, the spec
 * over the prototype's one). Flags are shown and cannot be changed here (S03 decision): the server sets them.
 */
export function PrefsScreen() {
  const me = useMe();
  const queries = useQueryClient();
  const toast = useToast();
  const signOut = useSignOut();
  const settings = useQuery({ queryKey: SETTINGS_KEY, queryFn: () => fetchSettings() });
  // what the user is typing; null shows the stored markup
  const [draft, setDraft] = useState<string | null>(null);
  const [markupErr, setMarkupErr] = useState(false);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const inFlight = useRef(0);

  const s = settings.data;
  const stored = s?.default_markup != null ? ratePercentText(s.default_markup) : "";
  const markup = draft ?? stored;

  /** Each change is built from the settings as they now are on screen, shown at once, and sent after the ones
   * before it: two quick changes (two brands) never send a stale copy of a dict that overwrites the first. The
   * server's answer replaces the screen's copy once nothing else is on its way. */
  function save(make: (cur: TenantSettings) => SettingsPatch, message?: string) {
    const cur = queries.getQueryData<TenantSettings>(SETTINGS_KEY);
    if (!cur) return;
    const body = make(cur);
    queries.setQueryData<TenantSettings>(SETTINGS_KEY, { ...cur, ...body } as TenantSettings);
    inFlight.current += 1;
    chain.current = chain.current.then(async () => {
      try {
        const next = await patchSettings(body);
        if (inFlight.current === 1) queries.setQueryData<TenantSettings>(SETTINGS_KEY, next);
        if (message) toast(message);
      } catch (err) {
        toast(err instanceof ApiError ? err.message : FALLBACK);
        void queries.invalidateQueries({ queryKey: SETTINGS_KEY });
      } finally {
        inFlight.current -= 1;
      }
    });
  }

  function saveMarkup() {
    if (markup.trim() === stored) {
      setDraft(null);
      setMarkupErr(false);
      return;
    }
    const rate = markupRate(markup);
    setMarkupErr(rate === null);
    if (rate === null) {
      toast("הזינו אחוז במספרים, עד 500");
      return;
    }
    setDraft(null);
    save(
      () => ({ default_markup: rate }),
      `התוספת על העלות עודכנה: ${markup.trim()}%. הצעות חדשות וחישוב מחדש ישתמשו בה`,
    );
  }

  function setBrand(family: string, brand: string) {
    save((cur) => {
      const prefs = Object.fromEntries(Object.entries(cur.brand_preferences).filter(([k]) => k !== family));
      if (brand) prefs[family] = brand;
      return { brand_preferences: prefs };
    });
  }

  function toggleInclude(part: EnclosurePart) {
    save(({ enclosure_includes_default: cur }) => ({ enclosure_includes_default: { ...cur, [part]: !cur[part] } }));
  }

  const quota = me.data ? quotaView(me.data.quota) : null;
  const flags = me.data?.flags ?? {};

  return (
    <Shell title="הגדרות">
      <section className="card set-sec">
        <div className="sec-head">
          <h2>חבילה ומגבלות</h2>
          <span className="chip acc">{me.data?.plan.name_he ?? "—"}</span>
        </div>
        <Row title="הצעות החודש" sub="נספרת רק הצעה שהקליטה שלה הצליחה. גרסה חדשה של אותו שרטוט לא נספרת">
          <span className="num" dir="ltr" data-testid="prefs-quota">
            {quota ? quota.label.replace(" מתוך ", " / ") : "—"}
          </span>
        </Row>
        <Row title="עמודים לקובץ">
          <span className="num">{me.data?.plan.max_pages_per_file ?? "—"}</span>
        </Row>
        <Row title="גודל קובץ">
          <span className="num">{MAX_FILE_MB}MB</span>
        </Row>
        <Row title="פורמטים" sub="DWG ו-DXF בגרסה 2.0">
          <span className="small">PDF · תמונה · אקסל · CSV</span>
        </Row>
      </section>

      <section className="card set-sec">
        <div className="sec-head">
          <h2>תמחור</h2>
        </div>
        <Row title="תוספת על העלות" sub="מהשאלה בכניסה. אפשר לשנות לכל משפחה בהמשך">
          <div className="row">
            <input
              className={`input num${markupErr ? " err" : ""}`}
              id="markup"
              style={{ width: 80, textAlign: "end" }}
              value={markup}
              inputMode="decimal"
              aria-label="תוספת באחוזים"
              disabled={!s}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={saveMarkup}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
              }}
            />
            <span>%</span>
          </div>
        </Row>
        {BRAND_ROWS.map((r) => (
          <Row key={r.family} title={r.label}>
            <select
              className="input"
              id={`pref-brand-${r.family}`}
              style={{ width: "auto" }}
              aria-label={r.label}
              disabled={!s}
              value={s?.brand_preferences[r.family] ?? ""}
              onChange={(e) => setBrand(r.family, e.target.value)}
            >
              <option value="">ללא העדפה</option>
              {BRANDS.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </Row>
        ))}
      </section>

      <section className="card set-sec">
        <div className="sec-head">
          <h2>מה כלול במחיר הארון</h2>
          <span className="small muted">כדי שלא יתומחר פעמיים</span>
        </div>
        {INCLUDES.map((i) => (
          <Row key={i.part} title={i.label}>
            <Toggle
              label={i.label}
              on={!!s?.enclosure_includes_default[i.part]}
              disabled={!s}
              testId={`include-${i.part}`}
              onChange={() => toggleInclude(i.part)}
            />
          </Row>
        ))}
      </section>

      <section className="card set-sec">
        <div className="sec-head">
          <h2>ברירות מחדל</h2>
        </div>
        <Row title="זרם זליגה 30mA לפחת, כשלא כתוב" sub="ברירת מחדל של המערכת. מוצגת בשורה, ולא הופכת אותה לצהובה">
          <Toggle
            label="זרם זליגה 30mA לפחת, כשלא כתוב"
            on={s ? rcd30(s.attribute_defaults) : false}
            disabled={!s}
            testId="rcd30"
            onChange={() =>
              save(({ attribute_defaults: cur }) => ({ attribute_defaults: withRcd30(cur, !rcd30(cur)) }))
            }
          />
        </Row>
      </section>

      <section className="card set-sec" data-testid="flags">
        <div className="sec-head">
          <h2>תכונות בדגלים</h2>
          <span className="small muted">בגרסה 1.0, כל אחת מאחורי דגל. נקבעות בשרת לכל מפעל, ולא משתנות כאן</span>
        </div>
        {FLAG_ROWS.map((f) => (
          <Row
            key={f.key}
            title={
              <>
                {f.name} <span className="v2">דגל</span>
              </>
            }
            sub={f.desc}
          >
            <Toggle label={f.name} on={!!flags[f.key]} disabled />
          </Row>
        ))}
      </section>

      <section className="card set-sec">
        <div className="sec-head">
          <h2>חשבון</h2>
        </div>
        <div className="set-row">
          <div>
            <b>משתמש</b>
            <br />
            <span className="small muted mono">{me.data?.user.email}</span>
          </div>
          <span className="chip">בעלים</span>
        </div>
        <Row title="משתמשים נוספים" sub="בגרסה הבאה">
          <button type="button" className="btn sm" disabled>
            הזמן
          </button>
        </Row>
        <Row title="יציאה">
          <button type="button" className="btn sm" data-testid="logout-prefs" onClick={signOut}>
            <Icon name="out" />
            יציאה
          </button>
        </Row>
      </section>
    </Shell>
  );
}
