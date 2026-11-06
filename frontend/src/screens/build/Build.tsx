/**
 * The chat quote builder (13 §4.2, S27; prototype `vBuild`, lines 1331–1357): the conversation beside the draft.
 * Each message goes to the server, which reads it, changes the draft's rows and runs stages 4–7; the answer is the
 * whole build, so the table is the quote as the review screen will show it. A price typed on an unpriced row asks
 * "לעדכן גם במחירון?" as in review (S27 decision 3). "פתח במסך הבדיקה" opens the draft like any quote.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useLocation, useNavigate, useParams } from "react-router";

import {
  ApiError,
  fetchBuild,
  lineAction,
  sendBuildMessage,
  sendBuildVoice,
  settleBuildMessage,
  startBuild,
  undoAction,
  undoBuild,
  type Build,
  type BuildMessage,
  type QuoteLine,
} from "../../api/client";
import { useMe } from "../../api/QueryProvider";
import { quotaView } from "../../shell/quota";
import { Shell } from "../../shell/Shell";
import { Icon } from "../../ui/Icon";
import { Modal } from "../../ui/Modal";
import { useToast } from "../../ui/Toast";
import { parseAmount, shekels } from "../review/model";
import {
  draftCounts,
  draftRows,
  draftTotal,
  droppedText,
  EMPTY_DRAFT,
  extras,
  INTRO_TEXT,
  pending,
  PLACEHOLDER,
  qtyOf,
  shownMessages,
  understood,
  type DraftRow,
} from "./model";
import { useRecorder } from "./recorder";

const FAILED = "לא הצלחנו לשלוח. נסו שוב";
// The prototype's note under the field (line 1345), while the transcriber is the stand-in (until S29)
const VOICE_NOTE =
  "ההקלטה עדיין מדומה: כל הקלטה נשמעת כמו המשפט לדוגמה. בהמשך: תמלול עברית ונרמול מונחים, ואז אותו מסלול כמו כתב כמויות";

function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : FAILED;
}

export function BuildScreen() {
  const me = useMe();
  const { drawingId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const [build, setBuild] = useState<Build | null>(null);
  const [sending, setSending] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [pricing, setPricing] = useState<{ line: QuoteLine; amount: string } | null>(null);
  const msgs = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const first = useRef(false);
  const id = drawingId ?? build?.drawing_id ?? null;
  const blocked = me.data ? quotaView(me.data.quota).blocked : false;
  const voice = Boolean(me.data?.flags.voice_input);

  // `/build` after a build: a new one (React Router keeps this component between the two paths)
  const [routeId, setRouteId] = useState(drawingId);
  if (routeId !== drawingId) {
    setRouteId(drawingId);
    if (!drawingId) setBuild(null);
  }

  useEffect(() => {
    if (!drawingId || build?.drawing_id === drawingId) return;
    fetchBuild(drawingId)
      .then(setBuild)
      .catch((e: unknown) => toast(errorText(e)));
  }, [drawingId, build?.drawing_id, toast]);

  useEffect(() => {
    msgs.current?.scrollTo({ top: msgs.current.scrollHeight });
  }, [build?.messages.length, sending]);

  // The first line makes the quote and counts it (S27 decision 2): the quota meter and the recent list follow
  const counted = useRef<string | null>(null);
  function refreshCounts(quoteId: string) {
    void qc.invalidateQueries({ queryKey: ["quotes"] });
    if (counted.current === quoteId) return;
    counted.current = quoteId;
    void qc.invalidateQueries({ queryKey: ["me"] });
    void qc.invalidateQueries({ queryKey: ["home-summary"] });
  }

  async function send(message: string) {
    const t = message.trim();
    if (!t || sending) return;
    setSending(t);
    try {
      const b = id ? await sendBuildMessage(id, t) : await startBuild(t);
      setBuild(b);
      if (!drawingId) navigate(`/build/${b.drawing_id}`, { replace: true });
      if (b.quote_id) refreshCounts(b.quote_id);
    } catch (e) {
      setText(t);
      toast(errorText(e));
    } finally {
      setSending(null);
    }
  }

  /** A recording: transcribed on the server, then its card waits for "הוסף" or "תקן" (S27 decision 1). */
  async function hear(audio: Blob, seconds: number) {
    setSending("…");
    try {
      const b = await sendBuildVoice(id, audio, seconds);
      setBuild(b);
      if (!drawingId) navigate(`/build/${b.drawing_id}`, { replace: true });
    } catch (e) {
      toast(errorText(e));
    } finally {
      setSending(null);
    }
  }

  async function settle(messageId: string, how: "apply" | "dismiss", heard: string | null) {
    if (!id) return;
    try {
      const b = await settleBuildMessage(id, messageId, how);
      setBuild(b);
      if (how === "dismiss" && heard) {
        setText(heard);
        input.current?.focus();
      }
      if (b.quote_id) refreshCounts(b.quote_id);
    } catch (e) {
      toast(errorText(e));
    }
  }

  const recorder = useRecorder(
    (audio, seconds) => void hear(audio, seconds),
    (t) => toast(t),
  );
  const recording = recorder.state === "recording";

  // The request typed on the chat home is the first message (13 §4.3); its mic starts a recording here
  useEffect(() => {
    const state = location.state as { text?: string; record?: boolean } | null;
    if (drawingId || first.current || !(state?.text || state?.record)) return;
    first.current = true;
    const t = state.text;
    window.setTimeout(() => (t ? void send(t) : voice ? void recorder.start() : undefined), 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, for what home sent
  }, []);

  function submit(e: FormEvent) {
    e.preventDefault();
    const t = text;
    setText("");
    void send(t);
  }

  async function undo() {
    if (!id) return;
    try {
      setBuild(await undoBuild(id));
      toast("השינוי האחרון בוטל");
    } catch (e) {
      toast(errorText(e));
    }
  }

  function onPriceKey(line: QuoteLine, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const amount = parseAmount(e.currentTarget.value);
    if (amount === null) {
      toast("הזינו מחיר ליחידה, במספרים");
      return;
    }
    setPricing({ line, amount });
  }

  async function savePrice(save: boolean) {
    const p = pricing;
    const quoteId = build?.quote_id;
    if (!p || !quoteId || !id) return;
    setPricing(null);
    try {
      const done = await lineAction(quoteId, p.line.line_id, { kind: "price-entry", unit_price: p.amount, save });
      setBuild(await fetchBuild(id));
      const eventId = done.event_id;
      toast(
        save ? `נשמר במחירון: ${p.line.description}, ${shekels(p.amount)}` : done.message,
        eventId
          ? {
              onUndo: () =>
                void undoAction(quoteId, eventId)
                  .then(() => fetchBuild(id))
                  .then(setBuild)
                  .catch((e: unknown) => toast(errorText(e))),
            }
          : undefined,
      );
    } catch (e) {
      toast(errorText(e));
    }
  }

  const rows = draftRows(build?.quote);
  const more = extras(build?.quote);
  const shown = shownMessages(build);

  return (
    <Shell title="הצעה בצ'אט">
      <div className="build">
        <section className="card build-chat" aria-labelledby="build-chat-title">
          <div className="sec-head">
            <h2 id="build-chat-title">שיחה</h2>
            <span className="v2">דגל</span>
          </div>
          <div className="msgs" id="msgs" ref={msgs} data-testid="build-msgs" aria-live="polite">
            {shown.length === 0 && !sending ? <div className="msg a">{INTRO_TEXT}</div> : null}
            {shown.map((m) => (
              <Message
                key={m.message_id}
                m={m}
                onAdd={() => void settle(m.message_id, "apply", m.heard)}
                onFix={() => void settle(m.message_id, "dismiss", m.heard)}
              />
            ))}
            {sending ? (
              <>
                <div className="msg u">{sending}</div>
                <div className="msg a typing" data-testid="build-typing" aria-label="בונה את השורות">
                  <span />
                  <span />
                  <span />
                </div>
              </>
            ) : null}
          </div>
          <form className="chat-in" id="build-form" onSubmit={submit}>
            {voice ? (
              <button
                type="button"
                className={`round${recording ? " rec" : ""}`}
                data-testid="mic"
                aria-label={recording ? "מקליט. לחצו כדי לעצור" : "הקלטה קולית"}
                aria-pressed={recording}
                disabled={Boolean(sending) || Boolean(pending(build))}
                onClick={recorder.toggle}
              >
                <Icon name="mic" />
              </button>
            ) : null}
            <label htmlFor="build-input" className="visually-hidden">
              מה יש בלוח
            </label>
            <input
              ref={input}
              className="input"
              id="build-input"
              data-testid="build-input"
              placeholder={recording ? "מקליט…" : PLACEHOLDER}
              autoComplete="off"
              value={text}
              disabled={recording || (blocked && !build?.quote_id)}
              onChange={(e) => setText(e.target.value)}
            />
            <button className="btn primary" type="submit" aria-label="שלח" disabled={!text.trim() || Boolean(sending)}>
              <Icon name="send" />
            </button>
          </form>
          {voice && build?.voice_stand_in !== false ? <div className="small muted build-note">{VOICE_NOTE}</div> : null}
        </section>
        <section className="card" aria-labelledby="build-draft-title">
          <div className="sec-head">
            <h2 id="build-draft-title">טיוטת ההצעה</h2>
            <span className="spacer" />
            {rows.length ? (
              <span className="small muted" data-testid="build-counts">
                {draftCounts(rows)}
              </span>
            ) : null}
          </div>
          {rows.length ? (
            <>
              <div className="tbl-wrap">
                <table className="tbl" data-testid="build-lines">
                  <thead>
                    <tr>
                      <th>מוצר</th>
                      <th>כמות</th>
                      <th>ליחידה</th>
                      <th>סה"כ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <DraftLine key={r.line.line_id} row={r} onPriceKey={onPriceKey} />
                    ))}
                    {more.count ? (
                      <tr className="muted" data-testid="build-extras">
                        <td>פריטים נלווים ועבודה ({more.count})</td>
                        <td className="n" />
                        <td className="n" />
                        <td className="n">{shekels(more.total)}</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
              <div className="lines-foot">
                <span>
                  סה"כ{" "}
                  <b className="num" data-testid="build-total">
                    {draftTotal(build?.quote)}
                  </b>
                </span>
                <span className="spacer" />
                {build?.can_undo ? (
                  <button type="button" className="btn ghost sm" data-testid="build-undo" onClick={() => void undo()}>
                    בטל את השינוי האחרון
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn primary sm"
                  data-testid="build-open"
                  onClick={() => build?.quote_id && navigate(`/review/${build.quote_id}`)}
                >
                  פתח במסך הבדיקה
                </button>
              </div>
            </>
          ) : (
            <div className="pad muted">{EMPTY_DRAFT}</div>
          )}
        </section>
      </div>
      {pricing ? (
        <Modal onClose={() => setPricing(null)} labelledBy="build-price-title">
          <h2 id="build-price-title">לעדכן גם במחירון?</h2>
          <span>
            הזנת מחיר <b className="num">{shekels(pricing.amount)}</b> ל<b>{pricing.line.description}</b>.
          </span>
          <div className="small note-box">
            <span>
              <b>עדכון במחירון:</b> הצעות חדשות ישתמשו במחיר הזה.
            </span>
            <span>
              <b>הצעות שנשלחו לא משתנות.</b> טיוטות פתוחות לא משתנות לבד, ויציגו שיש מחיר חדש.
            </span>
          </div>
          <div className="row">
            <button type="button" className="btn primary" data-testid="price-db" onClick={() => void savePrice(true)}>
              עדכן גם במחירון
            </button>
            <button type="button" className="btn" data-testid="price-here" onClick={() => void savePrice(false)}>
              רק בהצעה הזו
            </button>
            <span className="spacer" />
            <button type="button" className="btn ghost" onClick={() => setPricing(null)}>
              ביטול
            </button>
          </div>
        </Modal>
      ) : null}
    </Shell>
  );
}

function Message({ m, onAdd, onFix }: { m: BuildMessage; onAdd: () => void; onFix: () => void }) {
  if (m.role === "assistant") return <div className="msg a">{m.text}</div>;
  const dropped = m.status === "undone" ? [] : droppedText(m);
  const bubble = (
    <div className={`msg u${m.status === "undone" ? " undone" : ""}`} data-testid="build-user-msg">
      {m.heard != null ? (
        <span className="small" style={{ opacity: 0.8 }}>
          שמעתי: "{m.heard}"
        </span>
      ) : (
        m.text
      )}
      {m.status === "undone" ? <span className="small"> (בוטל)</span> : null}
      {dropped.length && m.status !== "pending" ? <span className="visually-hidden">{dropped.join(". ")}</span> : null}
    </div>
  );
  if (m.status !== "pending") return bubble;
  const lines = understood(m);
  return (
    <>
      {bubble}
      <div className="prop" data-testid="voice-card">
        <b>{lines.length ? "הבנתי:" : "לא הבנתי רכיבים מההקלטה."}</b>
        {lines.length ? (
          <ul className="voice-lines">
            {lines.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        ) : null}
        {dropped.length ? <span className="small muted">לא נקלט: {dropped.join(". ")}</span> : null}
        {m.question ? <span className="small">{m.question}</span> : null}
        <div className="row">
          {lines.length ? (
            <button type="button" className="btn primary sm" data-testid="voice-add" onClick={onAdd}>
              הוסף
            </button>
          ) : null}
          <button type="button" className="btn sm" data-testid="voice-fix" onClick={onFix}>
            תקן
          </button>
        </div>
      </div>
    </>
  );
}

function DraftLine({
  row,
  onPriceKey,
}: {
  row: DraftRow;
  onPriceKey: (line: QuoteLine, e: KeyboardEvent<HTMLInputElement>) => void;
}) {
  const { line } = row;
  return (
    <tr data-testid="build-line" data-status={line.status}>
      <td>
        {line.description} {row.panel ? <span className="chip">{row.panel}</span> : null}
        {row.chips.map((c) => (
          <span key={c.text} className={`chip ${c.tone}`}>
            {c.text}
          </span>
        ))}
      </td>
      <td className="n">{qtyOf(line)}</td>
      <td className="n">
        {row.priced ? (
          shekels(line.unit_price)
        ) : (
          <input
            className="price-in"
            style={{ width: 80 }}
            data-testid="build-price"
            placeholder="מחיר"
            inputMode="decimal"
            aria-label={`מחיר ל${line.description}`}
            onKeyDown={(e) => onPriceKey(line, e)}
          />
        )}
      </td>
      <td className="n">{row.priced ? shekels(line.line_total) : "—"}</td>
    </tr>
  );
}
