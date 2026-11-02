import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type DragEvent } from "react";
import { Navigate, useSearchParams } from "react-router";

import { ApiError, fetchProgress, uploadAudit, type Me, type UploadedFile } from "../../api/client";
import { useMe } from "../../api/QueryProvider";
import { quotaView } from "../../shell/quota";
import { Shell } from "../../shell/Shell";
import { Icon } from "../../ui/Icon";
import { useToast } from "../../ui/Toast";
import { ConfirmStep, FailedStep, isActive, POLL_MS, RunStep } from "../newQuote/NewQuote";
import { applyServerCheck, clientCheck, sizeText, type PickedFile } from "../newQuote/model";
import { auditStartState, quoteCheck } from "./model";

const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";

/**
 * A new audit (11 §4; S16 decision 4): the drawing and the existing quote, then the new-quote screen's run,
 * page-confirmation and BOM-mapping steps for stages 1–4 and the audit step, then the results. No prototype screen:
 * the new-quote flow's look (prototype `vNew`). `/audit?drawing=drw_…` shows a run, so a reload comes back to it.
 */
export function NewAuditScreen() {
  const me = useMe();
  const queries = useQueryClient();
  const [params, setParams] = useSearchParams();
  const drawingId = params.get("drawing");
  const progress = useQuery({
    queryKey: ["progress", drawingId],
    queryFn: () => fetchProgress(drawingId ?? ""),
    enabled: drawingId !== null,
    refetchInterval: (q) => (isActive(q.state.data) ? POLL_MS : false),
  });
  const p = progress.data;
  const ready = p?.status === "ready" && p.audit_id;
  useEffect(() => {
    if (ready) for (const key of ["me", "home-summary"]) void queries.invalidateQueries({ queryKey: [key] });
  }, [ready, queries]);

  let body;
  if (!me.data) body = null;
  else if (ready) return <Navigate to={`/audit/${p.audit_id}`} replace />;
  else if (drawingId && !p)
    body = progress.isError ? (
      <p className="err-msg" role="alert">
        לא הצלחנו לטעון את הבדיקה. נסו לרענן את הדף
      </p>
    ) : null;
  else if (p && p.status === "awaiting_confirmation")
    body = <ConfirmStep progress={p} me={me.data} onCancelled={() => setParams({})} />;
  else if (p && isActive(p)) body = <RunStep progress={p} onCancelled={() => setParams({})} />;
  else if (p && p.status === "failed") body = <FailedStep progress={p} onBack={() => setParams({})} />;
  else body = <PickStep me={me.data} onStarted={(id) => setParams({ drawing: id })} />;
  return <Shell title="בדיקת הצעה קיימת">{body}</Shell>;
}

let nextKey = 0;
const picked = (file: File, check: typeof clientCheck): PickedFile => ({
  key: `a${(nextKey += 1)}`,
  file,
  error: check(file),
});

function PickStep({ me, onStarted }: { me: Me; onStarted: (drawingId: string) => void }) {
  const queries = useQueryClient();
  const toast = useToast();
  const [project, setProject] = useState("");
  const [drawings, setDrawings] = useState<PickedFile[]>([]);
  const [quote, setQuote] = useState<PickedFile | null>(null);
  const [busy, setBusy] = useState(false);
  const start = auditStartState({ drawings, quote, remaining: quotaView(me.quota).remaining, busy });

  async function begin() {
    if (!quote) return;
    setBusy(true);
    try {
      const result = await uploadAudit({ files: drawings.map((f) => f.file), quote: quote.file, project });
      void queries.invalidateQueries({ queryKey: ["me"] });
      onStarted(result.drawing_id);
    } catch (err) {
      if (err instanceof ApiError && err.code === "upload_rejected") {
        const perFile = err.details.filter((d) => "name" in d) as unknown as UploadedFile[];
        setDrawings(applyServerCheck(drawings, perFile));
        setQuote(applyServerCheck([quote], perFile)[0] ?? quote);
        const general = err.details.find((d) => !("name" in d));
        if (general && typeof general.message === "string") toast(general.message);
      } else toast(err instanceof ApiError ? err.message : FALLBACK);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="card pad" style={{ display: "grid", gap: 14 }}>
        <h2>מה בודקים?</h2>
        <span className="small muted">
          מעלים שרטוט ואת הצעת המחיר שכבר הכנתם עליו. המערכת מראה מה חסר בהצעה, מה נספר פעמיים ומה לא תואם לשרטוט, לפי
          המחירים של ההצעה עצמה. שום דבר לא משתנה בלי אישור שלכם.
        </span>
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="audit-proj">פרויקט / שם הלוח</label>
          <input
            className="input"
            id="audit-proj"
            value={project}
            onChange={(e) => setProject(e.target.value)}
            placeholder="לא חובה: נמלא מטבלת הכותרת"
            autoComplete="off"
          />
        </div>
      </section>

      <div className="audit-picks">
        <FilePick
          id="audit-drawing"
          testId="drop-drawing"
          title="השרטוט"
          hint="PDF, תמונות, אקסל או ZIP · עד 20MB לקובץ"
          multiple
          files={drawings}
          onAdd={(list) => setDrawings([...drawings, ...list.map((f) => picked(f, clientCheck))])}
          onRemove={(key) => setDrawings(drawings.filter((f) => f.key !== key))}
        />
        <FilePick
          id="audit-quote"
          testId="drop-quote"
          title="ההצעה הקיימת"
          hint="קובץ אחד: PDF, צילום, אקסל או CSV"
          files={quote ? [quote] : []}
          onAdd={(list) => setQuote(list[0] ? picked(list[0], quoteCheck) : quote)}
          onRemove={() => setQuote(null)}
        />
      </div>

      <div className="card startbar">
        <span
          className={`small ${start.isError ? "err-msg" : "muted"}`}
          style={{ flex: 1, minWidth: 200 }}
          data-testid="start-note"
        >
          {start.text}
        </span>
        <button
          type="button"
          className="btn primary"
          data-testid="start-audit"
          disabled={!start.canStart}
          onClick={() => void begin()}
        >
          התחל בדיקה
        </button>
      </div>
    </>
  );
}

function FilePick(props: {
  id: string;
  testId: string;
  title: string;
  hint: string;
  multiple?: boolean;
  files: PickedFile[];
  onAdd: (files: File[]) => void;
  onRemove: (key: string) => void;
}) {
  const [over, setOver] = useState(false);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    props.onAdd([...e.dataTransfer.files]);
  };
  return (
    <section className="card" style={{ overflow: "hidden" }} aria-label={props.title}>
      <label
        className={`drop${over ? " over" : ""}`}
        htmlFor={props.id}
        data-testid={props.testId}
        style={{ borderRadius: props.files.length ? "var(--r-lg) var(--r-lg) 0 0" : "var(--r-lg)", margin: 0 }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        <Icon name={props.multiple ? "upload" : "doc"} />
        <b>{props.title}</b>
        <span className="small muted">{props.hint}</span>
        <input
          id={props.id}
          className="visually-hidden"
          type="file"
          multiple={props.multiple}
          onChange={(e) => {
            props.onAdd([...(e.target.files ?? [])]);
            e.target.value = "";
          }}
        />
      </label>
      {props.files.length > 0 && (
        <div role="list" aria-label={`${props.title}: הקבצים שנבחרו`}>
          {props.files.map((f) => (
            <div
              className="file-row"
              role="listitem"
              key={f.key}
              style={{ gridTemplateColumns: "auto minmax(0,1fr) auto auto" }}
            >
              <span className="kind-ico">
                <Icon name="doc" />
              </span>
              <span style={{ minWidth: 0 }}>
                <span className="mono wrap-any">{f.file.name}</span>{" "}
                <span className="small muted">{sizeText(f.file.size)}</span>
                {f.error && <div className="err-msg">{f.error.message}</div>}
              </span>
              <span className={`chip ${f.error ? "bad" : "ok"}`}>{f.error ? "נדחה" : "תקין"}</span>
              <button
                type="button"
                className="btn ghost sm"
                aria-label={`הסר את ${f.file.name}`}
                onClick={() => props.onRemove(f.key)}
              >
                <Icon name="x" />
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
