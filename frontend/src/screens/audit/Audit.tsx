import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import {
  ApiError,
  createCorrectedQuote,
  decideDifference,
  fetchAudit,
  type Audit,
  type AuditDifference,
  type RejectReason,
} from "../../api/client";
import { Shell } from "../../shell/Shell";
import { Icon } from "../../ui/Icon";
import { Modal } from "../../ui/Modal";
import { useToast } from "../../ui/Toast";
import { INPUT_KINDS } from "../newQuote/model";
import { DrawingPane } from "../review/Drawing";
import { shekels } from "../review/model";
import { useUndo } from "../review/undo";
import type { FocusRequest } from "../review/Viewer";
import {
  coversSeveral,
  correctedText,
  decidable,
  decisionText,
  firstBoxPage,
  groups,
  headline,
  kpis,
  matchedLines,
  moneyText,
  qtyText,
  REJECT_REASONS,
  title,
  TYPE_CHIPS,
  whereText,
} from "./model";

const POLL_MS = 2000; // a link to an audit that still runs: look again until it is ready
const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";
const SHELL_TITLE = "בדיקת הצעה קיימת";

type Decision = { status: AuditDifference["status"]; reject_reason?: RejectReason; note?: string };

/**
 * The audit's results (11 §7, prototype `vAudit`; S16 decision 1): the prototype's single column, with the spec's
 * decision on each difference, the "לבדוק" group, and "הצג בשרטוט" in the review screen's drawing pane.
 */
export function AuditScreen() {
  const { auditId = "" } = useParams();
  const audit = useQuery({
    queryKey: ["audit", auditId],
    queryFn: () => fetchAudit(auditId),
    refetchInterval: (q) => (q.state.data?.status === "processing" ? POLL_MS : false),
  });
  let body;
  if (audit.data?.status === "ready") body = <Results audit={audit.data} />;
  else if (audit.data) body = <NotReady audit={audit.data} />;
  else if (audit.isError)
    body = (
      <div className="card pad" style={{ display: "grid", gap: 12, justifyItems: "start" }}>
        <p className="err-msg" role="alert" style={{ margin: 0 }}>
          {audit.error instanceof ApiError && audit.error.status === 404
            ? "הבדיקה לא נמצאה"
            : "לא הצלחנו לטעון את הבדיקה. נסו לרענן את הדף"}
        </p>
        <Link className="btn sm" to="/audit">
          בדיקה חדשה
        </Link>
      </div>
    );
  return <Shell title={SHELL_TITLE}>{body ?? null}</Shell>;
}

function NotReady({ audit }: { audit: Audit }) {
  const failed = audit.status === "failed";
  return (
    <div className="card pad" style={{ display: "grid", gap: 12, justifyItems: "start" }} data-testid="audit-waiting">
      <span className={`chip ${failed ? "bad" : "warn"}`}>{failed ? "הבדיקה נכשלה" : "הבדיקה עדיין רצה"}</span>
      <b className="wrap-any">{audit.drawing_name}</b>
      {failed ? (
        <Link className="btn primary sm" to="/audit">
          בדיקה חדשה
        </Link>
      ) : (
        <Link className="btn sm" to={`/audit?drawing=${audit.drawing_id}`}>
          לצפייה בהתקדמות
        </Link>
      )}
    </div>
  );
}

function Results({ audit }: { audit: Audit }) {
  const queries = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const undo = useUndo(audit.audit_id);
  const [rejecting, setRejecting] = useState<AuditDifference | null>(null);
  const [showing, setShowing] = useState<AuditDifference | null>(null);
  const [making, setMaking] = useState(false);
  const g = groups(audit.differences);
  const k = kpis(audit);
  const s = audit.summary;
  const quoteTotal = audit.quote_ref?.total_before_vat;
  const [kind] = INPUT_KINDS[audit.input_kind ?? ""] ?? [];
  const matched = matchedLines(audit);
  const several = matched.filter(coversSeveral).length;

  async function decide(d: AuditDifference, next: Decision, label: string) {
    const before: Decision =
      d.status === "rejected" && d.reject_reason
        ? { status: "rejected", reject_reason: d.reject_reason, note: d.reject_note ?? undefined }
        : { status: d.status };
    const put = async (decision: Decision) => {
      const saved = await decideDifference(audit.audit_id, d.diff_id, decision);
      queries.setQueryData<Audit>(["audit", audit.audit_id], (a) =>
        a ? { ...a, differences: a.differences.map((x) => (x.diff_id === saved.diff_id ? saved : x)) } : a,
      );
    };
    try {
      await put(next);
      undo.record({ label, undo: () => put(before) });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
      void queries.invalidateQueries({ queryKey: ["audit", audit.audit_id] });
    }
  }

  async function corrected() {
    setMaking(true);
    try {
      const quoteId = audit.corrected_quote_id ?? (await createCorrectedQuote(audit.audit_id));
      if (!audit.corrected_quote_id) toast(correctedText(audit));
      void queries.invalidateQueries({ queryKey: ["quotes"] });
      navigate(`/review/${quoteId}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
      setMaking(false);
    }
  }

  const row = (d: AuditDifference) => (
    <DifferenceRow
      key={d.diff_id}
      d={d}
      audit={audit}
      onConfirm={() => void decide(d, { status: "confirmed" }, `אושר: ${title(d, audit.lines)}`)}
      onReject={() => setRejecting(d)}
      onReopen={() => void decide(d, { status: "open" }, `ההחלטה בוטלה: ${title(d, audit.lines)}`)}
      onShow={() => setShowing(d)}
    />
  );

  return (
    <>
      <div className="card pad row" style={{ gap: 16 }}>
        <div className="wrap-any" style={{ display: "grid", gap: 2, flex: "1 1 220px" }}>
          <span className="eyebrow">שרטוט</span>
          <span className="mono wrap-any">{audit.drawing_file_name ?? audit.drawing_name}</span>
          <span className="small muted">
            {[audit.drawing_number, `${audit.pages.length} עמודים`, kind].filter(Boolean).join(" · ")}
          </span>
        </div>
        <div className="wrap-any" style={{ display: "grid", gap: 2, flex: "1 1 220px" }}>
          <span className="eyebrow">הצעה קיימת</span>
          <span className="mono wrap-any">{audit.quote_file_name ?? "—"}</span>
          <span className="small muted">
            {[`${s?.quote_lines ?? audit.lines.length} שורות`, quoteTotal ? `${shekels(quoteTotal)} לפני מע"מ` : null]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </div>
        <Link className="btn" to="/audit" data-testid="new-audit">
          <Icon name="upload" />
          בדיקה חדשה
        </Link>
      </div>

      <p className="audit-headline" data-testid="audit-headline">
        {headline(audit)}
      </p>

      <div className="kpis" data-testid="kpis">
        <div className="card kpi">
          <span className="eyebrow">שורות תואמות</span>
          <b className="num">{k.matched}</b>
          <span className="small muted">כמות ומוצר זהים</span>
        </div>
        <div className={`card kpi${k.omissions ? " bad" : ""}`}>
          <span className="eyebrow">השמטות</span>
          <b className="num">{k.omissions}</b>
          <span className="small muted">{k.units === 1 ? "יחידה אחת" : `${k.units} יחידות`}</span>
        </div>
        <div className={`card kpi${k.omissions ? " bad" : ""}`}>
          <span className="eyebrow">כסף בסיכון</span>
          <b className="num">{`${k.atRisk}${k.unpriced ? "+" : ""}`}</b>
          <span className="small muted">לפי המחירים בהצעה עצמה</span>
        </div>
        <div className="card kpi">
          <span className="eyebrow">לא הבדל</span>
          <b className="num">{k.notDifferences}</b>
          <span className="small muted">חומר עזר אצל המפעל</span>
        </div>
      </div>

      <section className="card" aria-labelledby="diffs-h">
        <div className="sec-head">
          <h2 id="diffs-h">ההבדלים</h2>
          <span className="spacer" />
          <button
            type="button"
            className="btn primary sm"
            data-testid="corrected-quote"
            disabled={making}
            onClick={() => void corrected()}
          >
            {audit.corrected_quote_id ? "פתח את ההצעה המתוקנת" : "צור הצעה מתוקנת"}
          </button>
        </div>
        {g.shown.length || g.info.length ? (
          <DiffTable testId="diffs">{[...g.shown, ...g.info].map(row)}</DiffTable>
        ) : (
          <p className="pad small muted" style={{ margin: 0 }}>
            לא נמצאו הבדלים
          </p>
        )}
      </section>

      {g.toCheck.length > 0 && (
        <section className="card" aria-labelledby="check-h">
          <div className="sec-head">
            <h2 id="check-h">לבדוק</h2>
            <span className="small muted">ביטחון נמוך: ייתכן שזו טעות של המערכת</span>
          </div>
          <DiffTable testId="to-check">{g.toCheck.map(row)}</DiffTable>
        </section>
      )}

      <section className="card" aria-labelledby="matched-h">
        <div className="sec-head">
          <h2 id="matched-h">שורות שתאמו</h2>
          {several > 0 && (
            <span className="small muted">
              {several === 1 ? "שורה אחת בהצעה מכסה כמה מכשירים" : `${several} שורות בהצעה מכסות כמה מכשירים`}
            </span>
          )}
        </div>
        <div className="tbl-wrap">
          <table className="tbl" data-testid="matched">
            <thead>
              <tr>
                <th>שורה בהצעה</th>
                <th>כמות</th>
                <th>ליחידה</th>
                <th>בשרטוט</th>
              </tr>
            </thead>
            <tbody>
              {matched.map((ln) => (
                <tr key={ln.index}>
                  <td>
                    {ln.description}
                    {coversSeveral(ln) && (
                      <>
                        {" "}
                        <span className="chip acc">מכסה כמה מכשירים</span>
                      </>
                    )}
                  </td>
                  <td className="n">{qtyText(ln.qty)}</td>
                  <td className="n">{shekels(ln.unit_price)}</td>
                  <td className="small">
                    {ln.designators.length ? (
                      <span dir="ltr" className="mono">
                        {ln.designators.join(", ")}
                      </span>
                    ) : (
                      <span className="muted">{ln.includes.join(", ") || "—"}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {rejecting && (
        <RejectDialog
          name={title(rejecting, audit.lines)}
          onClose={() => setRejecting(null)}
          onSave={(reason, note) => {
            const d = rejecting;
            setRejecting(null);
            const label = REJECT_REASONS.find(([r]) => r === reason)?.[1] ?? "";
            void decide(
              d,
              { status: "rejected", reject_reason: reason, note: note || undefined },
              `נדחה (${label}): ${title(d, audit.lines)}`,
            );
          }}
        />
      )}
      {showing && <EvidenceDialog d={showing} audit={audit} onClose={() => setShowing(null)} />}
    </>
  );
}

function DiffTable({ testId, children }: { testId: string; children: ReactNode }) {
  return (
    <div className="tbl-wrap">
      <table className="tbl" data-testid={testId}>
        <thead>
          <tr>
            <th>מה</th>
            <th>בשרטוט</th>
            <th>בהצעה</th>
            <th>כסף בסיכון</th>
            <th>ראיה</th>
            <th>החלטה</th>
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function DifferenceRow(props: {
  d: AuditDifference;
  audit: Audit;
  onConfirm: () => void;
  onReject: () => void;
  onReopen: () => void;
  onShow: () => void;
}) {
  const { d, audit } = props;
  const name = title(d, audit.lines);
  const [chip, tone] = TYPE_CHIPS[d.type];
  const money = moneyText(d);
  const decided = decisionText(d);
  const red = d.shown && d.severity === "high" && d.status !== "rejected";
  return (
    <tr className={red ? "diff-row" : undefined} data-testid="diff" data-type={d.type} data-status={d.status}>
      <td>
        <b>{name}</b>
        <br />
        <span className={`chip ${tone}`.trim()}>{chip}</span>
        <div className="small muted diff-msg">{d.message}</div>
      </td>
      <td className="n">{qtyText(d.drawing_qty)}</td>
      <td className="n">{qtyText(d.quote_qty)}</td>
      <td className={`n${money.muted ? " muted" : ""}`}>{money.text}</td>
      <td>
        <div className="diff-ev">
          {d.designators.map((t) => (
            <span key={t} className="des">
              {t}
            </span>
          ))}
          <span className="small muted">{whereText(d)}</span>
        </div>
        {d.boxes.length > 0 && (
          <button
            type="button"
            className="btn ghost sm"
            data-testid="show-on-drawing"
            aria-label={`הצג בשרטוט: ${name}`}
            onClick={props.onShow}
          >
            <Icon name="eye" />
            הצג בשרטוט
          </button>
        )}
      </td>
      <td>
        {!decidable(d) ? (
          <span className="small muted">—</span>
        ) : decided ? (
          <div className="diff-ev">
            <span className={`chip ${d.status === "confirmed" ? "ok" : ""}`.trim()} data-testid="decision">
              {decided}
            </span>
            <button
              type="button"
              className="btn ghost sm"
              aria-label={`שנה את ההחלטה: ${name}`}
              onClick={props.onReopen}
            >
              שנה
            </button>
          </div>
        ) : (
          <div className="diff-ev">
            <button
              type="button"
              className="btn sm"
              data-testid="confirm-diff"
              aria-label={`נכון, זה הבדל: ${name}`}
              onClick={props.onConfirm}
            >
              נכון, זה הבדל
            </button>
            <button
              type="button"
              className="btn ghost sm"
              data-testid="reject-diff"
              aria-label={`לא נכון: ${name}`}
              onClick={props.onReject}
            >
              לא נכון
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

function RejectDialog(props: { name: string; onClose: () => void; onSave: (r: RejectReason, note: string) => void }) {
  const [reason, setReason] = useState<RejectReason | null>(null);
  const [note, setNote] = useState("");
  return (
    <Modal onClose={props.onClose} labelledBy="reject-h">
      <h2 id="reject-h" style={{ margin: 0, fontSize: 16 }}>
        למה זה לא הבדל?
      </h2>
      <span className="small muted wrap-any">{props.name}</span>
      <fieldset className="reasons" aria-label="סיבה">
        {REJECT_REASONS.map(([value, label]) => (
          <label key={value} className="reason">
            <input
              type="radio"
              name="reject-reason"
              value={value}
              checked={reason === value}
              onChange={() => setReason(value)}
            />
            {label}
          </label>
        ))}
      </fieldset>
      <div className="field">
        <label htmlFor="reject-note">הערה (לא חובה)</label>
        <input
          id="reject-note"
          className="input"
          value={note}
          maxLength={500}
          onChange={(e) => setNote(e.target.value)}
          autoComplete="off"
        />
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button type="button" className="btn ghost" onClick={props.onClose}>
          ביטול
        </button>
        <button
          type="button"
          className="btn primary"
          data-testid="save-reject"
          disabled={reason === null}
          onClick={() => reason && props.onSave(reason, note.trim())}
        >
          שמור
        </button>
      </div>
    </Modal>
  );
}

/** "הצג בשרטוט" (11 §7: the components marked on every page they are on), in the review screen's drawing pane. */
function EvidenceDialog({ d, audit, onClose }: { d: AuditDifference; audit: Audit; onClose: () => void }) {
  const name = title(d, audit.lines);
  const [pageId, setPageId] = useState<string | null>(() => firstBoxPage(d, audit.pages));
  const [focus, setFocus] = useState<FocusRequest | null>(() => {
    const box = d.boxes.find((b) => b.page_id === pageId);
    return box ? { pageId: box.page_id, bbox: box.bbox, mode: "frame", nonce: 1 } : null;
  });
  const onPage = (id: string) => {
    setPageId(id);
    const box = d.boxes.find((b) => b.page_id === id);
    setFocus((f) => (box ? { pageId: id, bbox: box.bbox, mode: "frame", nonce: (f?.nonce ?? 0) + 1 } : null));
  };
  return (
    <Modal onClose={onClose} labelledBy="evidence-h" className="wide evidence">
      <div className="row">
        <h2 id="evidence-h" className="wrap-any" style={{ margin: 0, fontSize: 16, flex: 1, minWidth: 0 }}>
          {name}
        </h2>
        <button type="button" className="btn ghost sm" aria-label="סגור" onClick={onClose}>
          <Icon name="x" />
        </button>
      </div>
      <span className="small muted">{d.message}</span>
      <div className="drawing-pane evidence-pane" data-testid="evidence-drawing">
        <DrawingPane
          pages={audit.pages}
          overlays={(page) =>
            d.boxes
              .filter((b) => b.page_id === page.page_id)
              .map((b, i) => ({
                key: `${d.diff_id}:${i}`,
                lineId: d.diff_id,
                bbox: b.bbox,
                tone: "r" as const,
                selected: false,
                dimmed: false,
                label: name,
              }))
          }
          pageId={pageId}
          onPage={onPage}
          activePanelId={null}
          showPanels={false}
          focus={focus}
          finding={null}
          onSelectLine={() => undefined}
          onSelectPanel={() => undefined}
        />
      </div>
    </Modal>
  );
}
