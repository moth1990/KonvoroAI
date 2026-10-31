import { useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";

import type { HomeSummary, Me, QuoteListItem } from "../api/client";
import { useHomeSummary, useMe, useQuotes } from "../api/QueryProvider";
import { countText, shekelsFloor, weekdayText, whenText } from "../format";
import { quotaView, type QuotaView } from "../shell/quota";
import { Shell } from "../shell/Shell";
import { Icon } from "../ui/Icon";
import { useToast } from "../ui/Toast";
import { homeRoute, homeSuggestions } from "./homeRoute";

/** Classic home, or the chat home when `home_chat` is on (13 §4.3). The server evaluates the flag. */
export function HomeScreen() {
  const me = useMe();
  if (!me.data) return <Shell title="">{me.isError ? <LoadError /> : null}</Shell>;
  return me.data.flags.home_chat ? <ChatHome me={me.data} /> : <ClassicHome me={me.data} />;
}

function LoadError() {
  return (
    <p className="err-msg" role="alert">
      לא הצלחנו לטעון את הנתונים. נסו לרענן את הדף
    </p>
  );
}

function statusChip(q: QuoteListItem): [string, string] {
  if (q.version_status === "sent") return [`נשלח · גרסה ${q.version}`, "ok"];
  if (q.missing_prices > 0)
    return [countText(q.missing_prices, "טיוטה · שורה בלי מחיר", (n) => `טיוטה · ${n} בלי מחיר`), "bad"];
  return ["טיוטה", "acc"];
}

function QuoteRow({ quote, when }: { quote: QuoteListItem; when?: string }) {
  const [label, tone] = statusChip(quote);
  return (
    <Link className="list-item" to={`/review/${quote.id}`}>
      <span className="kind-ico">
        <Icon name="pen" />
      </span>
      <span style={{ minWidth: 0 }}>
        <span className="ttl">{quote.name}</span>
        <br />
        <span className="small muted">{`גרסה ${quote.version}`}</span>
      </span>
      {when === undefined ? (
        <span className={`chip ${tone}`}>{label}</span>
      ) : (
        <span style={{ display: "grid", justifyItems: "end", gap: 4 }}>
          <span className={`chip ${tone}`}>{label}</span>
          <span className="small muted">{when}</span>
        </span>
      )}
    </Link>
  );
}

/** "New quote" as a link, or a disabled button at the quota limit, pointing at the banner's reason (01 §4.5). */
function NewQuoteAction({ quota, className, children }: { quota: QuotaView; className: string; children: ReactNode }) {
  if (quota.blocked)
    return (
      <button type="button" className={className} disabled aria-describedby="quota-banner" data-testid="new-quote">
        {children}
      </button>
    );
  return (
    <Link className={className} to="/new" data-testid="new-quote">
      {children}
    </Link>
  );
}

function StatTile({
  eyebrow,
  value,
  pct,
  warn,
  note,
}: {
  eyebrow: string;
  value: string;
  pct: number | null;
  warn?: boolean;
  note: string;
}) {
  return (
    <div className="card stat">
      <span className="eyebrow">{eyebrow}</span>
      <b className="num">{value}</b>
      {pct !== null && (
        <div className={`meter${warn ? " warn" : ""}`} aria-hidden="true">
          <i style={{ width: `${pct}%` }} />
        </div>
      )}
      <span className="small muted">{note}</span>
    </div>
  );
}

function waitingItems(summary: HomeSummary) {
  return [
    ...summary.missing_prices.map((m) => ({
      key: `p-${m.quote_id}`,
      to: `/review/${m.quote_id}`,
      icon: "tag" as const,
      color: "var(--bad)",
      title: countText(m.count, "מחיר חסר אחד", (n) => `${n} מחירים חסרים`),
      sub: `${m.quote_name}. כל מחיר שתזין נשמר למחירון`,
    })),
    ...(summary.queue_pending > 0
      ? [
          {
            key: "queue",
            to: "/queue",
            icon: "queue" as const,
            color: "var(--accent)",
            title: countText(summary.queue_pending, "פריט אחד בתור האישור", (n) => `${n} פריטים בתור האישור`),
            sub: "ידע שמועמד לשכבה המשותפת",
          },
        ]
      : []),
    ...summary.audit_omissions.map((a) => ({
      key: `a-${a.audit_id}`,
      to: "/audit",
      icon: "audit" as const,
      color: "var(--warn)",
      title: countText(a.count, "השמטה אחת", (n) => `${n} השמטות`) + (a.quote_number ? ` בהצעה ${a.quote_number}` : ""),
      sub: a.amount_at_risk ? `לפחות ${shekelsFloor(a.amount_at_risk)} בסיכון` : "עדיין בלי מחיר",
    })),
  ];
}

/** Classic home (prototype `vHome`, lines 716–751). */
function ClassicHome({ me }: { me: Me }) {
  const quota = quotaView(me.quota);
  const quotes = useQuotes(5);
  const summary = useHomeSummary();
  const now = new Date();
  const tz = me.tenant.timezone;
  const waiting = summary.data ? waitingItems(summary.data) : [];
  const capacity = quota.label.replace(" מתוך ", " / ");

  return (
    <Shell title="שלום">
      <div className="cta-row">
        <NewQuoteAction quota={quota} className="btn primary">
          <Icon name="plus" />
          הצעה חדשה משרטוט
        </NewQuoteAction>
        <Link className="btn" to="/audit">
          <Icon name="audit" />
          בדיקת הצעה קיימת
        </Link>
      </div>
      <div className="stats">
        <StatTile
          eyebrow="הצעות החודש"
          value={capacity}
          pct={quota.pct}
          warn={quota.tone !== "ok"}
          note={`חבילת ${me.plan.name_he} · מתחדש ב-${quota.renews}`}
        />
        {/* No data until pricing and review land (S22, S23): "—" keeps the prototype's layout (S04 decision). */}
        <StatTile eyebrow="כיסוי מחירון" value="—" pct={0} note="אין עדיין נתונים" />
        <StatTile eyebrow="שורות שאושרו בלי תיקון" value="—" pct={0} note="אין עדיין נתונים" />
      </div>
      <div className="grid-2">
        <section className="card" aria-labelledby="recent-title">
          <div className="sec-head">
            <h2 id="recent-title">עבודה אחרונה</h2>
          </div>
          <div className="list" data-testid="recent">
            {quotes.data?.length === 0 && <p className="list-empty">עדיין אין הצעות. ההצעה הראשונה מתחילה משרטוט</p>}
            {quotes.data?.map((q) => (
              <QuoteRow key={q.id} quote={q} when={whenText(q.updated_at, now, tz)} />
            ))}
          </div>
        </section>
        <section className="card" aria-labelledby="waiting-title">
          <div className="sec-head">
            <h2 id="waiting-title">מחכה לך</h2>
          </div>
          <div className="list" data-testid="waiting">
            {summary.data && waiting.length === 0 && <p className="list-empty">אין כרגע משהו שמחכה לך</p>}
            {waiting.map((w) => (
              <Link className="list-item" to={w.to} key={w.key}>
                <span className="kind-ico" style={{ color: w.color }}>
                  <Icon name={w.icon} />
                </span>
                <span>
                  <span className="ttl">{w.title}</span>
                  <br />
                  <span className="small muted">{w.sub}</span>
                </span>
                <span />
              </Link>
            ))}
          </div>
        </section>
      </div>
      {(quotes.isError || summary.isError) && <LoadError />}
    </Shell>
  );
}

function remainingEyebrow(quota: QuotaView): string | null {
  if (quota.remaining === null) return null;
  if (quota.remaining === 0) return "לא נותרו הצעות החודש";
  return countText(quota.remaining, "הצעה אחת נותרה החודש", (n) => `${n} הצעות נותרו החודש`);
}

/** Chat home (`home_chat`, prototype `vHomeChat` and `homeSubmit`, lines 1253–1284). No mic until S27. */
function ChatHome({ me }: { me: Me }) {
  const quota = quotaView(me.quota);
  const quotes = useQuotes(4);
  const navigate = useNavigate();
  const toast = useToast();
  const [text, setText] = useState("");
  const builder = Boolean(me.flags.chat_quote_builder);
  const eyebrow = [weekdayText(new Date(), me.tenant.timezone), remainingEyebrow(quota)].filter(Boolean).join(" · ");

  function go(request: string) {
    const route = homeRoute(request, me.flags);
    if (!route) return;
    if (route.kind === "toast") toast(route.text);
    else navigate(route.to, { state: route.text ? { text: route.text } : undefined });
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    go(text);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      go(text);
    }
  }

  return (
    <Shell title="">
      <div className="hero">
        <span className="eyebrow">{eyebrow}</span>
        <h1>מה בונים היום?</h1>
        <form className="prompt" id="home-form" onSubmit={submit}>
          <label htmlFor="home-input" className="visually-hidden">
            מה בונים היום
          </label>
          <textarea
            id="home-input"
            data-testid="home-input"
            placeholder={builder ? "תארו לוח, הדביקו כתב כמויות, או צרפו שרטוט" : "צרפו שרטוט, או כתבו איזו הצעה לבדוק"}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
          />
          <div className="prompt-bar">
            <NewQuoteAction quota={quota} className="round">
              <Icon name="clip" />
              <span className="visually-hidden">צרף שרטוט או קובץ</span>
            </NewQuoteAction>
            <span className="spacer" />
            {builder && <span className="small muted">השורות נבנות מהמחירון שלך</span>}
            <button className="round primary" type="submit" aria-label="שלח">
              <Icon name="send" />
            </button>
          </div>
        </form>
        <div className="hero-sugg">
          {homeSuggestions(me.flags).map((q) => (
            <button key={q} type="button" className="fchip" data-testid="home-sugg" onClick={() => go(q)}>
              {q}
            </button>
          ))}
        </div>
      </div>
      <section className="card home-recent" aria-labelledby="recent-title">
        <div className="sec-head">
          <h2 id="recent-title">אחרונים</h2>
          <span className="spacer" />
          {!quota.blocked && (
            <Link className="small" to="/new">
              הצעה משרטוט
            </Link>
          )}
        </div>
        <div className="list" data-testid="recent">
          {quotes.data?.length === 0 && <p className="list-empty">עדיין אין הצעות</p>}
          {quotes.data?.map((q) => (
            <QuoteRow key={q.id} quote={q} />
          ))}
        </div>
      </section>
      {quotes.isError && <LoadError />}
    </Shell>
  );
}
