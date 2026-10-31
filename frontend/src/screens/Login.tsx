import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { ApiError, login, requestPasswordReset } from "../api/client";
import { getToken } from "../api/token";
import { returnTo } from "../auth/auth";
import { Logo } from "../ui/Icon";
import { useToast } from "../ui/Toast";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export const LOGIN_ERRORS = {
  email: "כתובת האימייל לא תקינה",
  password: "הסיסמה צריכה להיות באורך 8 תווים לפחות",
  resetNeedsEmail: "כדי לאפס סיסמה, כתבו קודם את כתובת האימייל",
} as const;

export const RESET_SENT = "אם הכתובת רשומה אצלנו, נשלח אליה קישור לאיפוס";
const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";

/** The prototype's checks (submit handler, line 1599): the email first, then the password length. */
export function validateLogin(
  email: string,
  password: string,
): { field: "email" | "password"; message: string } | null {
  if (!EMAIL.test(email)) return { field: "email", message: LOGIN_ERRORS.email };
  if (password.length < 8) return { field: "password", message: LOGIN_ERRORS.password };
  return null;
}

/** Login (prototype `vLogin`, lines 660–688). The demo hint and the "prototype" tag are left out. */
export function LoginScreen() {
  const navigate = useNavigate();
  const location = useLocation();
  const queries = useQueryClient();
  const toast = useToast();
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [error, setError] = useState<{ field: "email" | "password" | null; message: string } | null>(null);
  const [busy, setBusy] = useState(false);

  if (getToken() !== null) return <Navigate to={returnTo(location.state)} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const invalid = validateLogin(email, password);
    if (invalid) {
      setError(invalid);
      (invalid.field === "email" ? emailRef : passwordRef).current?.focus();
      return;
    }
    setBusy(true);
    try {
      await login(email, password);
      queries.clear();
      navigate(returnTo(location.state), { replace: true });
    } catch (err) {
      setError({ field: null, message: err instanceof ApiError ? err.message : FALLBACK });
      setBusy(false);
    }
  }

  async function forgot() {
    if (!EMAIL.test(email)) {
      setError({ field: "email", message: LOGIN_ERRORS.resetNeedsEmail });
      emailRef.current?.focus();
      return;
    }
    setError(null);
    try {
      await requestPasswordReset(email);
      toast(RESET_SENT);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
    }
  }

  return (
    <div className="login">
      <section className="login-brand">
        <Logo />
        <div style={{ display: "grid", gap: 14 }}>
          <h1>מהשרטוט להצעת מחיר, שורה אחרי שורה</h1>
          <p>המערכת קוראת את התוכנית, מתאימה כל רכיב למחירון שלך, ומסמנת בצבע מה כדאי לבדוק לפני שההצעה יוצאת.</p>
          <div className="busbars" aria-hidden="true">
            {["L1", "L2", "L3", "N"].map((bar) => (
              <div className="busbar" key={bar}>
                <span>{bar}</span>
                <i />
              </div>
            ))}
          </div>
        </div>
        <span />
      </section>
      <section className="login-form">
        <form id="login-form" noValidate onSubmit={submit} aria-labelledby="login-title">
          <div style={{ display: "grid", gap: 4 }}>
            <h2 id="login-title" style={{ fontSize: 22 }}>
              כניסה
            </h2>
            <span className="muted">משתמש אחד לכל מפעל בגרסה 1.0</span>
          </div>
          <div className="field">
            <label htmlFor="email">אימייל</label>
            <input
              ref={emailRef}
              className={`input${error?.field === "email" ? " err" : ""}`}
              id="email"
              type="email"
              dir="ltr"
              autoComplete="email"
              value={email}
              aria-invalid={error?.field === "email"}
              aria-describedby="login-err"
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">סיסמה</label>
            <div className="pw">
              <input
                ref={passwordRef}
                className={`input${error?.field === "password" ? " err" : ""}`}
                id="password"
                type={shown ? "text" : "password"}
                dir="ltr"
                autoComplete="current-password"
                placeholder="לפחות 8 תווים"
                value={password}
                aria-invalid={error?.field === "password"}
                aria-describedby="login-err"
                onChange={(e) => setPassword(e.target.value)}
              />
              <button
                type="button"
                data-testid="pw"
                aria-pressed={shown}
                aria-controls="password"
                onClick={() => setShown(!shown)}
              >
                {shown ? "הסתר" : "הצג"}
              </button>
            </div>
          </div>
          <div id="login-err" className="err-msg" role="alert">
            {error?.message}
          </div>
          <button
            className="btn primary"
            type="submit"
            disabled={busy}
            style={{ justifyContent: "center", padding: 10 }}
          >
            כניסה
          </button>
          <div className="row small">
            <button type="button" className="btn ghost sm" data-testid="forgot" onClick={forgot}>
              שכחתי סיסמה
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
