import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, approveCandidate, fetchCandidates, rejectCandidate, type Candidate } from "../../api/client";
import { useMe } from "../../api/QueryProvider";
import { Shell } from "../../shell/Shell";
import { useToast } from "../../ui/Toast";
import { APPROVED_TOAST, KIND_LABEL, originText, REJECTED_TOAST } from "./model";

const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";
const QUEUE_KEY = ["knowledge-candidates"];

/**
 * The pilot approval queue (00 §14.2, prototype `vQueue`, lines 1210–1226). A correction in a quote changes only
 * this factory, at once; only "אשר לשכבה המשותפת" here sends knowledge to every factory, stamped `pilot_engineer`.
 */
export function QueueScreen() {
  const me = useMe();
  const queries = useQueryClient();
  const toast = useToast();
  const list = useQuery({ queryKey: QUEUE_KEY, queryFn: () => fetchCandidates() });
  const [busy, setBusy] = useState<string | null>(null);
  const tz = me.data?.tenant.timezone ?? "Asia/Jerusalem";

  async function decide(c: Candidate, ok: boolean) {
    setBusy(c.id);
    try {
      await (ok ? approveCandidate(c.id) : rejectCandidate(c.id));
      toast(ok ? APPROVED_TOAST : REJECTED_TOAST);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
    } finally {
      setBusy(null);
      await queries.invalidateQueries({ queryKey: QUEUE_KEY });
      void queries.invalidateQueries({ queryKey: ["home-summary"] });
    }
  }

  const items = list.data?.items ?? [];
  const pending = items.filter((c) => c.status === "pending");
  const done = items.filter((c) => c.status !== "pending");

  const card = (c: Candidate) => (
    <div className="qcard" key={c.id} data-testid="qcard">
      <div style={{ display: "grid", gap: 4, minWidth: 0 }}>
        <div className="row">
          <span className="chip acc">{KIND_LABEL[c.kind]}</span>
          <b className="wrap-any">{c.what}</b>
        </div>
        <span className="small muted">ראיה: {c.evidence}</span>
        <span className="small muted">מקור: {originText(c, tz)}</span>
      </div>
      {c.status === "pending" ? (
        <div className="acts">
          <button
            type="button"
            className="btn primary sm"
            data-testid="qok"
            disabled={busy !== null}
            onClick={() => void decide(c, true)}
          >
            אשר לשכבה המשותפת
          </button>
          <button
            type="button"
            className="btn sm"
            data-testid="qno"
            disabled={busy !== null}
            onClick={() => void decide(c, false)}
          >
            דחה
          </button>
        </div>
      ) : (
        <span className={`chip${c.status === "approved" ? " ok" : ""}`}>
          {c.status === "approved" ? "אושר · pilot_engineer" : "נדחה · נשאר במפעל"}
        </span>
      )}
    </div>
  );

  return (
    <Shell title="תור אישור">
      <div
        className="card pad"
        style={{ display: "grid", gap: 6, background: "var(--accent-soft)", borderColor: "transparent" }}
      >
        <b>חודש הפיילוט: מהנדס המפעל מאשר מה עובר לשכבה המשותפת</b>
        <span className="small">
          תיקון בהצעה משפיע מיד, אבל רק אצלכם. רק אישור כאן מעביר ידע לכל המפעלים. מחירים, העדפות והתבניות שלכם לא
          עוברים אף פעם.
        </span>
      </div>
      <section className="card" aria-labelledby="queue-pending">
        <div className="sec-head">
          <h2 id="queue-pending">ממתין לאישור</h2>
          <span className="chip" data-testid="pending-count">
            {pending.length}
          </span>
        </div>
        {list.isError ? (
          <div className="pad muted">{list.error instanceof ApiError ? list.error.message : FALLBACK}</div>
        ) : pending.length ? (
          pending.map(card)
        ) : list.isSuccess ? (
          <div className="pad muted">
            אין פריטים ממתינים. פריט חדש נכנס לכאן כשתיקון שלך יכול לעזור גם למפעלים אחרים.
          </div>
        ) : null}
      </section>
      {done.length ? (
        <section className="card" aria-labelledby="queue-done">
          <div className="sec-head">
            <h2 id="queue-done">טופל</h2>
          </div>
          {done.map(card)}
        </section>
      ) : null}
    </Shell>
  );
}
