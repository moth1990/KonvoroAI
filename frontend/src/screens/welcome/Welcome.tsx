import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate } from "react-router";

import { answerOnboarding, ApiError, type Me } from "../../api/client";
import { Logo } from "../../ui/Icon";
import { BRANDS, DEFAULT_MARKUP, examplePrice, FAMILIES, markupRate, type Brand, type Family } from "./model";

const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";

/**
 * A new factory's entry (10 §5.1, S24 decision 1): two questions and the data terms, before the first drawing. The
 * prototype has no screen for it, so it is built from its card, input, chip and button classes. The brand question
 * can be skipped; the terms cannot. Everything here can be changed later on the settings screen.
 */
export function WelcomeScreen({ answered }: { answered: boolean }) {
  const queries = useQueryClient();
  const [markup, setMarkup] = useState(DEFAULT_MARKUP);
  const [brands, setBrands] = useState<Record<Family, Brand | null>>({ circuit_breaker: null, rcd: null });
  const [terms, setTerms] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Answered here: on to the first drawing. Answered before (a visit later): home.
  const [done, setDone] = useState(false);

  const rate = markupRate(markup);
  const example = examplePrice(markup);

  const pick = (family: Family, brand: Brand) =>
    setBrands((cur) => ({ ...cur, [family]: cur[family] === brand ? null : brand }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (rate === null) {
      setError("הזינו אחוז במספרים, עד 500");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await answerOnboarding({ markup: rate, brands, accept_terms: true });
      queries.setQueryData<Me>(["me"], (me) => (me ? { ...me, onboarding_required: false } : me));
      void queries.invalidateQueries({ queryKey: ["me"] });
      void queries.invalidateQueries({ queryKey: ["settings"] });
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : FALLBACK);
      setBusy(false);
    }
  }

  if (done) return <Navigate to="/new" replace />;
  if (answered) return <Navigate to="/home" replace />;

  return (
    <main className="welcome-page" dir="rtl">
      <form className="welcome" onSubmit={(e) => void submit(e)} noValidate>
        <Logo />
        <div style={{ display: "grid", gap: 4 }}>
          <h1 style={{ margin: 0 }}>שתי שאלות, ומתחילים</h1>
          <span className="muted">
            פחות משתי דקות. אחר כך מעלים שרטוט, והמחירון שלכם נבנה מתוך ההצעות. אפשר לשנות הכל בהגדרות.
          </span>
        </div>

        <section className="card q" aria-labelledby="q-markup">
          <h2 id="q-markup">כמה אחוזים אתם מוסיפים על מחיר העלות?</h2>
          <div className="row">
            <input
              className={`input num${rate === null ? " err" : ""}`}
              id="markup"
              style={{ width: 90, textAlign: "end" }}
              inputMode="decimal"
              value={markup}
              onChange={(e) => setMarkup(e.target.value)}
              aria-label="תוספת על מחיר העלות, באחוזים"
              aria-invalid={rate === null}
              aria-describedby="markup-example"
            />
            <span>%</span>
          </div>
          <span className="small muted" id="markup-example" data-testid="markup-example">
            {example ? (
              <>
                דוגמה: עלות{" "}
                <span className="num" dir="ltr">
                  ₪100
                </span>{" "}
                ← מחיר ללקוח{" "}
                <b className="num" dir="ltr">
                  {example}
                </b>
              </>
            ) : (
              "הזינו אחוז במספרים, עד 500"
            )}
          </span>
        </section>

        <section className="card q" aria-labelledby="q-brands">
          <div className="row" style={{ alignItems: "baseline" }}>
            <h2 id="q-brands">עם אילו מותגים אתם עובדים בדרך כלל?</h2>
            <span className="small muted">אפשר לדלג</span>
          </div>
          {FAMILIES.map((f) => (
            <div className="row" key={f.key} role="group" aria-label={f.label} style={{ flexWrap: "wrap" }}>
              <b style={{ minWidth: 88 }}>{f.label}:</b>
              <div className="choices">
                {BRANDS.map((b) => (
                  <button
                    key={b.value}
                    type="button"
                    className="btn sm"
                    aria-pressed={brands[f.key] === b.value}
                    data-testid={`brand-${f.key}-${b.value}`}
                    onClick={() => pick(f.key, b.value)}
                  >
                    {b.label}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <span className="small muted">בלי בחירה, ההתאמה בוחרת לפי הקטלוג ולומדת מההחלפות שלכם.</span>
        </section>

        <section className="card q" aria-labelledby="q-terms">
          <h2 id="q-terms">תנאי השימוש בנתונים</h2>
          <ul className="small" style={{ margin: 0, paddingInlineStart: 18, display: "grid", gap: 4 }}>
            <li>השרטוטים והתיקונים שלכם משמשים לשיפור המערכת.</li>
            <li>מחירים, הנחות, חוקי רווח, העדפות ולקוחות שלכם לא משותפים עם אף מפעל אחר, אף פעם.</li>
            <li>
              ידע כללי, כמו סימן, קיצור או פריט קטלוג, עובר לשכבה המשותפת רק באישור מפורש בתור האישור, ובלי פרטים מזהים.
            </li>
          </ul>
          <label className="terms">
            <input
              type="checkbox"
              checked={terms}
              onChange={(e) => setTerms(e.target.checked)}
              data-testid="accept-terms"
            />
            <span>
              קראתי ואני מאשר/ת את תנאי השימוש בנתונים{" "}
              <span className="small muted">
                (גרסה{" "}
                <span className="mono" dir="ltr">
                  2026-10
                </span>
                )
              </span>
            </span>
          </label>
        </section>

        {error && (
          <div className="err-msg" role="alert">
            {error}
          </div>
        )}
        <div className="row">
          <button type="submit" className="btn primary" disabled={!terms || busy} data-testid="welcome-start">
            מתחילים
          </button>
          {!terms && <span className="small muted">צריך לאשר את תנאי השימוש כדי להעלות שרטוט</span>}
        </div>
      </form>
    </main>
  );
}
