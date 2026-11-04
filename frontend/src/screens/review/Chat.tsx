import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";

import {
  ApiError,
  applyProposal,
  dismissProposal,
  fetchChat,
  newChat,
  sendChatMessage,
  type Chat as ChatData,
  type ChatApply,
  type ChatBlock,
  type ChatInstance,
  type ChatMessage,
  type ChatProposal,
  type ChatUiContext,
  type Quote,
  type QuoteLine,
} from "../../api/client";
import { Icon } from "../../ui/Icon";
import {
  amount,
  applyLabel,
  diffRows,
  greeting,
  lineLabel,
  optionLabel,
  REMEMBER,
  rememberChoices,
  rememberedText,
  segments,
  type Remember,
  STATE,
  SUGGESTIONS,
  totals,
  unchanged,
  warningTexts,
} from "./chatModel";

export type ChatFocus = {
  lineIds: string[];
  panelId?: string | null;
  statuses?: string[] | null;
  instances?: ChatInstance[]; // 08 §6.4 `focus`: the components to frame on the drawing
};

type Props = {
  quote: Quote;
  ui: ChatUiContext;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onClose?: () => void;
  onSelectLine: (lineId: string) => void;
  onFocus: (f: ChatFocus) => void;
  onShowInstance: (instance: ChatInstance) => void;
  onApplied: (done: ChatApply) => void;
  toast: (text: string) => void;
};

const placed = (m: ChatMessage, ids: string[] | null | undefined): ChatInstance[] =>
  (ids ?? []).map((i) => m.instances?.[i]).filter((x): x is ChatInstance => !!x);

/**
 * The chat on the review screen (08, 09 §6.7; prototype `vChat`, `propCard`, lines 1007–1064): a drawer over the
 * drawing on the desktop, the third tab on the phone. Every answer comes from the server's tools; a change is a card
 * that only "החל" applies, as one action the screen's undo takes back.
 */
export function ChatPanel({
  quote,
  ui,
  inputRef,
  onClose,
  onSelectLine,
  onFocus,
  onShowInstance,
  onApplied,
  toast,
}: Props) {
  const quoteId = quote.quote_id;
  const qc = useQueryClient();
  const chat = useQuery({ queryKey: ["chat", quoteId], queryFn: () => fetchChat(quoteId) });
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const msgsRef = useRef<HTMLDivElement>(null);
  const lines = new Map(quote.panels.flatMap((p) => p.lines).map((l) => [l.line_id, l] as const));

  const setChat = (fn: (c: ChatData) => ChatData) =>
    qc.setQueryData<ChatData>(["chat", quoteId], (c) => (c ? fn(c) : c));
  const putProposal = (p: ChatProposal) =>
    setChat((c) => ({ ...c, proposals: [...c.proposals.filter((x) => x.proposal_id !== p.proposal_id), p] }));

  const send = useMutation({
    mutationFn: (message: string) => sendChatMessage(quoteId, message, ui),
    onMutate: (message) => setPending(message),
    onSuccess: (turn) => {
      setChat((c) => ({
        ...c,
        conversation_id: c.conversation_id ?? "active",
        messages: [...c.messages, turn.user, turn.assistant],
        proposals: [...c.proposals, ...turn.proposals],
      }));
      for (const b of turn.assistant.blocks)
        if (b.type === "ui_action")
          onFocus({
            lineIds: b.line_ids ?? [],
            panelId: b.panel_id,
            statuses: b.statuses,
            instances: placed(turn.assistant, b.instance_ids),
          });
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "לא הצלחתי לבצע את זה. אפשר לנסות שוב, או לבצע במסך."),
    onSettled: () => setPending(null),
  });

  const fresh = useMutation({
    mutationFn: () => newChat(quoteId),
    onSuccess: (c) => qc.setQueryData(["chat", quoteId], c),
  });

  useEffect(() => {
    const m = msgsRef.current;
    if (m) m.scrollTop = m.scrollHeight;
  }, [chat.data?.messages.length, pending]);

  const ask = (q: string) => {
    if (!q.trim() || send.isPending) return;
    send.mutate(q.trim());
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = text;
    setText("");
    ask(q);
  };

  const apply = async (p: ChatProposal, remember: Remember) => {
    try {
      const done = await applyProposal(p.proposal_id, remember);
      putProposal(done.proposal);
      onApplied(done);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) void qc.invalidateQueries({ queryKey: ["chat", quoteId] });
      toast(e instanceof ApiError ? e.message : "לא הצלחנו לשמור. נסו שוב");
    }
  };
  const dismiss = async (p: ChatProposal) => {
    try {
      putProposal(await dismissProposal(p.proposal_id));
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "לא הצלחנו לשמור. נסו שוב");
    }
  };

  const data = chat.data;
  const proposals = new Map((data?.proposals ?? []).map((p) => [p.proposal_id, p] as const));

  return (
    <aside className="chat" aria-label="צ'אט" data-testid="chat">
      <div className="chat-head">
        <b>צ'אט על ההצעה</b>
        <span className="spacer" />
        <button type="button" className="btn ghost sm" data-testid="newchat" onClick={() => fresh.mutate()}>
          שיחה חדשה
        </button>
        {onClose ? (
          <button type="button" className="btn ghost sm chat-toggle" aria-label="סגור" onClick={onClose}>
            <Icon name="x" />
          </button>
        ) : null}
      </div>
      {data?.closed_count ? (
        <div className="old-convs" data-testid="old-convs">
          {data.closed_count === 1 ? "שיחה קודמת נשמרה" : `${data.closed_count} שיחות קודמות נשמרו`} לקריאה בלבד.
          ההחלטות מהן כבר בהצעה.
        </div>
      ) : null}
      <div className="msgs" id="msgs" ref={msgsRef} aria-live="polite">
        {data && !data.messages.length ? (
          <div className="msg a">
            {data.closed_count
              ? "שיחה חדשה. ההחלטות מהשיחה הקודמת כבר בהצעה, אז לא צריך לחזור עליהן."
              : greeting(quote)}
          </div>
        ) : null}
        {data?.messages.map((m) => (
          <Message
            key={m.message_id}
            m={m}
            lines={lines}
            proposals={proposals}
            onSelectLine={onSelectLine}
            onFocus={onFocus}
            onShowInstance={onShowInstance}
            onAsk={ask}
            onApply={apply}
            onDismiss={dismiss}
          />
        ))}
        {pending ? (
          <>
            <div className="msg u">{pending}</div>
            <div className="msg a typing" data-testid="chat-typing" aria-label="הצ'אט כותב">
              <span />
              <span />
              <span />
            </div>
          </>
        ) : null}
      </div>
      <div className="sugg">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            className="fchip"
            data-testid="ask"
            disabled={send.isPending}
            onClick={() => ask(s)}
          >
            {s}
          </button>
        ))}
      </div>
      <form className="chat-in" id="chat-form" onSubmit={submit}>
        <input
          ref={inputRef}
          className="input"
          id="chat-input"
          data-testid="chat-input"
          aria-label="הודעה לצ'אט"
          placeholder="כתבו פקודה או שאלה…"
          autoComplete="off"
          value={text}
          maxLength={2000}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" className="btn primary" aria-label="שלח" disabled={send.isPending || !text.trim()}>
          <Icon name="send" />
        </button>
      </form>
    </aside>
  );
}

type MessageProps = {
  m: ChatMessage;
  lines: Map<string, QuoteLine>;
  proposals: Map<string, ChatProposal>;
  onSelectLine: (id: string) => void;
  onFocus: (f: ChatFocus) => void;
  onShowInstance: (instance: ChatInstance) => void;
  onAsk: (q: string) => void;
  onApply: (p: ChatProposal, remember: Remember) => void;
  onDismiss: (p: ChatProposal) => void;
};

function Message({
  m,
  lines,
  proposals,
  onSelectLine,
  onFocus,
  onShowInstance,
  onAsk,
  onApply,
  onDismiss,
}: MessageProps) {
  if (m.role === "user") {
    const b = m.blocks[0];
    return b ? (
      <Text b={b} m={m} who="u" lines={lines} onSelectLine={onSelectLine} onShowInstance={onShowInstance} />
    ) : null;
  }
  const out = [];
  let i = 0;
  for (const b of m.blocks) {
    const key = `${m.message_id}-${i++}`;
    if (b.type === "text")
      out.push(
        <Text
          key={key}
          b={b}
          m={m}
          who="a"
          lines={lines}
          onSelectLine={onSelectLine}
          onShowInstance={onShowInstance}
        />,
      );
    else if (b.type === "clarification")
      out.push(
        <div key={key} className="sugg clar" role="group" aria-label="אפשרויות">
          {(b.options ?? []).map((o) => (
            <button key={o} type="button" className="fchip" onClick={() => onAsk(o)}>
              {optionLabel(o, m.quotes ?? {})}
            </button>
          ))}
        </div>,
      );
    else if (b.type === "proposal" && b.proposal_id) {
      const p = proposals.get(b.proposal_id);
      if (p)
        out.push(
          <ProposalCard
            key={key}
            p={p}
            lines={lines}
            onSelectLine={onSelectLine}
            onApply={onApply}
            onDismiss={onDismiss}
            onAsk={onAsk}
          />,
        );
    } else if (b.type === "ui_action" && placed(m, b.instance_ids).length) {
      const first = placed(m, b.instance_ids)[0];
      out.push(
        <button
          key={key}
          type="button"
          className="btn sm"
          style={{ justifySelf: "end" }}
          data-testid="show-instance"
          onClick={() => first && onShowInstance(first)}
        >
          <Icon name="eye" />
          הצג בשרטוט
        </button>,
      );
    } else if (b.type === "ui_action" && (b.line_ids?.length || b.statuses?.length))
      out.push(
        <button
          key={key}
          type="button"
          className="btn sm"
          style={{ justifySelf: "end" }}
          onClick={() => onFocus({ lineIds: b.line_ids ?? [], panelId: b.panel_id, statuses: b.statuses })}
        >
          <Icon name="eye" />
          הצג בטבלה
        </button>,
      );
    else if (b.type === "settings_link" && b.route)
      out.push(
        <Link key={key} className="btn sm" style={{ justifySelf: "end" }} to={b.route} data-testid="settings-link">
          פתח את ההגדרות
        </Link>,
      );
  }
  return <>{out}</>;
}

function Text({
  b,
  m,
  who,
  lines,
  onSelectLine,
  onShowInstance,
}: {
  b: ChatBlock;
  m: ChatMessage;
  who: "a" | "u";
  lines: Map<string, QuoteLine>;
  onSelectLine: (id: string) => void;
  onShowInstance: (instance: ChatInstance) => void;
}) {
  return (
    <div className={`msg ${who}`}>
      {segments(b.content ?? "").map((s, i) =>
        s.kind === "text" ? (
          <span key={i}>{s.text}</span>
        ) : s.kind === "quote" ? (
          // another quote by its name, which only the screen knows (S25b decision 1)
          <span key={i} className="chip quote-ref" data-testid="quote-ref">
            {m.quotes?.[s.quoteId] ?? "הצעה אחרת"}
          </span>
        ) : s.kind === "instance" ? (
          m.instances?.[s.instanceId] ? (
            <button
              key={i}
              type="button"
              className="chip acc line-ref"
              data-testid="instance-ref"
              aria-label="הצג את הרכיב בשרטוט"
              onClick={() => {
                const inst = m.instances?.[s.instanceId];
                if (inst) onShowInstance(inst);
              }}
            >
              <Icon name="eye" />
              בשרטוט
            </button>
          ) : null
        ) : s.kind === "line" ? (
          lines.has(s.lineId) ? (
            <button
              key={i}
              type="button"
              className="chip acc line-ref"
              data-testid="line-ref"
              onClick={() => onSelectLine(s.lineId)}
            >
              <span dir="ltr">{lineLabel(lines.get(s.lineId))}</span>
            </button>
          ) : null
        ) : (
          <b key={i} className="num" dir="ltr">
            {amount(m.money, s.ref)}
          </b>
        ),
      )}
    </div>
  );
}

function ProposalCard({
  p,
  lines,
  onSelectLine,
  onApply,
  onDismiss,
  onAsk,
}: {
  p: ChatProposal;
  lines: Map<string, QuoteLine>;
  onSelectLine: (id: string) => void;
  onApply: (p: ChatProposal, remember: Remember) => void;
  onDismiss: (p: ChatProposal) => void;
  onAsk: (q: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [remember, setRemember] = useState<Remember>("quote_only"); // always this quote first (S25b decision 3)
  const choices = rememberChoices(p);
  const remembered = rememberedText(p);
  const state = STATE[p.status];
  const rows = diffRows(p);
  const sums = totals(p);
  const warnings = [...unchanged(p), ...warningTexts(p)];
  const act = async (fn: (p: ChatProposal, remember: Remember) => void | Promise<void>) => {
    setBusy(true);
    try {
      await fn(p, remember);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="prop" data-testid="proposal">
      <div className="row">
        <b>הצעת שינוי</b>
        <span className="spacer" />
        <span className={`chip ${state.tone}`} data-testid="proposal-state">
          {state.text}
        </span>
      </div>
      <span className="small">
        {p.summary_he}
        {p.affected_line_count
          ? ` · ${p.affected_line_count === 1 ? "שורה אחת" : `${p.affected_line_count} שורות`}`
          : ""}
      </span>
      {rows.length ? (
        <div className="diff">
          {rows.map((r, i) => (
            <div key={i} className={r.note ? "noted" : undefined}>
              <s>
                {r.lineId && lines.has(r.lineId) ? (
                  <button type="button" className="link-btn" onClick={() => onSelectLine(r.lineId ?? "")}>
                    {r.before}
                  </button>
                ) : (
                  r.before
                )}
              </s>
              <span className="muted">←</span>
              <span>{r.after}</span>
              {r.note ? <span className="small note">{r.note}</span> : null}
            </div>
          ))}
        </div>
      ) : (
        <span className="small muted">שום שורה לא משתנה</span>
      )}
      {sums ? (
        <span className="small" data-testid="proposal-totals">
          לפני מע"מ:{" "}
          <span className="num" dir="ltr">
            {sums.before}
          </span>{" "}
          ←{" "}
          <b className="num" dir="ltr">
            {sums.after}
          </b>
        </span>
      ) : null}
      {warnings.map((w) => (
        <span key={w} className="small" style={{ color: "var(--bad)" }}>
          {w}
        </span>
      ))}
      {p.status === "pending" && choices.length ? (
        <div className="sugg remember" role="radiogroup" aria-label="מה לזכור" data-testid="remember">
          {choices.map((r) => (
            <button
              key={r}
              type="button"
              role="radio"
              aria-checked={remember === r}
              className="fchip"
              data-testid={`remember-${r}`}
              disabled={busy}
              onClick={() => setRemember(r)}
            >
              {REMEMBER[r]}
            </button>
          ))}
        </div>
      ) : null}
      {p.status === "applied" && remembered ? (
        <span className="small muted" data-testid="remembered">
          {remembered}
        </span>
      ) : null}
      {p.status === "pending" ? (
        <div className="row">
          <button
            type="button"
            className="btn primary sm"
            data-testid="apply"
            disabled={busy}
            onClick={() => void act(onApply)}
          >
            {applyLabel(p)}
          </button>
          <button
            type="button"
            className="btn sm"
            data-testid="dismiss"
            disabled={busy}
            onClick={() => void act(onDismiss)}
          >
            בטל
          </button>
          <span className="small muted">הסכומים מחושבים במערכת, לא במודל</span>
        </div>
      ) : p.status === "expired" ? (
        <div className="row">
          <button type="button" className="btn sm" onClick={() => onAsk(p.summary_he)}>
            ליצור מחדש
          </button>
          <span className="small muted">ההצעה עודכנה מאז שההצעה הוכנה</span>
        </div>
      ) : null}
    </div>
  );
}
