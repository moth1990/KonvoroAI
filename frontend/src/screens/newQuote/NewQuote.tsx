import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import {
  ApiError,
  cancelDrawing,
  changePageKind,
  confirmDrawing,
  fetchProgress,
  fetchRevisable,
  setBomColumns,
  uploadDrawing,
  type BomRole,
  type Me,
  type PageKind,
  type Progress,
  type UploadedFile,
} from "../../api/client";
import { useMe } from "../../api/QueryProvider";
import { countText } from "../../format";
import { quotaView } from "../../shell/quota";
import { Shell } from "../../shell/Shell";
import { Icon } from "../../ui/Icon";
import { useToast } from "../../ui/Toast";
import {
  applyServerCheck,
  BOM_BY,
  BOM_ROLES,
  bomPages,
  bomProblem,
  clientCheck,
  CONFIRM_REASONS,
  countedText,
  gridHint,
  INPUT_KINDS,
  PAGE_KINDS,
  pageNote,
  ROUTES,
  sizeText,
  stageCounter,
  stageRows,
  startState,
  type PickedFile,
} from "./model";

const POLL_MS = 1000; // S05 decision: polling, not SSE
const FALLBACK = "משהו השתבש אצלנו. נסו שוב בעוד רגע";

type Mode = "new" | "rev";

/**
 * New quote (01 §4.6, prototype `vNew`): pick files, watch the 7 stages, see the result.
 * `/new?drawing=drw_…` shows a run, so a reload or a link from home comes back to it.
 */
export function NewQuoteScreen() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const drawingId = params.get("drawing");
  const [mode, setMode] = useState<Mode>("new");
  const [customer, setCustomer] = useState("");
  const [project, setProject] = useState("");
  const [revisionOf, setRevisionOf] = useState("");
  const [files, setFiles] = useState<PickedFile[]>([]);

  const progress = useQuery({
    queryKey: ["progress", drawingId],
    queryFn: () => fetchProgress(drawingId ?? ""),
    enabled: drawingId !== null,
    refetchInterval: (q) => (isActive(q.state.data) ? POLL_MS : false),
  });

  const p = progress.data;
  const revision = p ? p.counted_as === "revision" : mode === "rev";
  const title = revision ? "גרסה חדשה" : "הצעה חדשה";

  let body;
  if (!me.data) body = null;
  else if (drawingId && !p) body = progress.isError ? <LoadError /> : null;
  else if (p && p.status === "awaiting_confirmation")
    body = <ConfirmStep progress={p} me={me.data} onCancelled={() => setParams({})} />;
  else if (p && isActive(p)) body = <RunStep progress={p} onCancelled={() => setParams({})} />;
  else if (p && p.status === "ready") body = <DoneStep progress={p} me={me.data} />;
  else if (p && p.status === "failed") body = <FailedStep progress={p} onBack={() => setParams({})} />;
  else
    body = (
      <PickStep
        me={me.data}
        mode={mode}
        setMode={setMode}
        customer={customer}
        setCustomer={setCustomer}
        project={project}
        setProject={setProject}
        revisionOf={revisionOf}
        setRevisionOf={setRevisionOf}
        files={files}
        setFiles={setFiles}
        onStarted={(id) => setParams({ drawing: id })}
      />
    );

  return <Shell title={title}>{body}</Shell>;
}

function isActive(p: Progress | undefined): boolean {
  return p !== undefined && ["uploaded", "processing"].includes(p.status);
}

function LoadError() {
  return (
    <p className="err-msg" role="alert">
      לא הצלחנו לטעון את הפענוח. נסו לרענן את הדף
    </p>
  );
}

let nextKey = 0;

function PickStep(props: {
  me: Me;
  mode: Mode;
  setMode: (m: Mode) => void;
  customer: string;
  setCustomer: (v: string) => void;
  project: string;
  setProject: (v: string) => void;
  revisionOf: string;
  setRevisionOf: (v: string) => void;
  files: PickedFile[];
  setFiles: (f: PickedFile[]) => void;
  onStarted: (drawingId: string) => void;
}) {
  const { me, mode, files, setFiles } = props;
  const queries = useQueryClient();
  const toast = useToast();
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const rev = mode === "rev";
  const quota = quotaView(me.quota);
  const revisable = useQuery({ queryKey: ["revisable"], queryFn: () => fetchRevisable(), enabled: rev });
  const maxPages = me.plan.max_pages_per_file;
  const start = startState({
    files,
    revision: rev,
    revisionOf: props.revisionOf,
    remaining: quota.remaining,
    busy,
  });

  function add(list: FileList | null) {
    if (!list) return;
    const picked = [...list].map((file) => ({ key: `f${(nextKey += 1)}`, file, error: clientCheck(file) }));
    setFiles([...files, ...picked]);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    add(e.dataTransfer.files);
  }

  async function begin() {
    setBusy(true);
    try {
      const result = await uploadDrawing({
        files: files.map((f) => f.file),
        customer: props.customer,
        project: props.project,
        revisionOf: rev ? props.revisionOf : undefined,
      });
      setFiles(applyServerCheck(files, result.files));
      void queries.invalidateQueries({ queryKey: ["me"] });
      props.onStarted(result.drawing_id);
    } catch (err) {
      if (err instanceof ApiError && err.code === "upload_rejected") {
        const perFile = err.details.filter((d) => "name" in d) as unknown as UploadedFile[];
        setFiles(applyServerCheck(files, perFile));
        const general = err.details.find((d) => !("name" in d));
        if (general && typeof general.message === "string") toast(general.message);
      } else {
        toast(err instanceof ApiError ? err.message : FALLBACK);
        if (err instanceof ApiError && err.code === "quota_reached")
          void queries.invalidateQueries({ queryKey: ["me"] });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="card pad" style={{ display: "grid", gap: 14 }}>
        <div className="row">
          <h2 style={{ flex: 1 }}>מה מעלים?</h2>
          <div className="seg" role="group" aria-label="סוג ההעלאה">
            <button type="button" data-testid="upmode-new" aria-pressed={!rev} onClick={() => props.setMode("new")}>
              הצעה חדשה
            </button>
            <button type="button" data-testid="upmode-rev" aria-pressed={rev} onClick={() => props.setMode("rev")}>
              גרסה חדשה של שרטוט קיים
            </button>
          </div>
        </div>
        {rev ? (
          <div className="form2">
            <div className="field">
              <label htmlFor="rev-of">ההצעה הקיימת</label>
              <select
                className="input"
                id="rev-of"
                value={props.revisionOf}
                onChange={(e) => props.setRevisionOf(e.target.value)}
              >
                <option value="">בחרו הצעה</option>
                {revisable.data?.map((r) => (
                  <option key={r.drawing_id} value={r.drawing_id}>
                    {`${r.name} · גרסה ${r.version} · ${dayMonth(r.updated_at)}`}
                  </option>
                ))}
              </select>
            </div>
            <div className="small muted" style={{ alignSelf: "end" }}>
              גרסה חדשה לא נספרת במכסה. במסך הבדיקה יוצג מה השתנה מול הגרסה הקודמת, וההחלטות שכבר קיבלתם עוברות אליה.
            </div>
          </div>
        ) : (
          <>
            <div className="form2">
              <div className="field">
                <label htmlFor="up-cust">לקוח</label>
                <input
                  className="input"
                  id="up-cust"
                  value={props.customer}
                  onChange={(e) => props.setCustomer(e.target.value)}
                  placeholder="שם הלקוח"
                  autoComplete="off"
                />
              </div>
              <div className="field">
                <label htmlFor="up-proj">פרויקט / שם הלוח</label>
                <input
                  className="input"
                  id="up-proj"
                  value={props.project}
                  onChange={(e) => props.setProject(e.target.value)}
                  placeholder="למשל: גן ילדים, לוח ראשי"
                  autoComplete="off"
                />
              </div>
            </div>
            <span className="small muted">
              לא חובה. אם משאירים ריק, המערכת ממלאת מטבלת הכותרת של השרטוט, ואפשר לשנות אחר כך.
            </span>
          </>
        )}
      </section>

      <section className="card" style={{ overflow: "hidden" }}>
        <label
          className={`drop${over ? " over" : ""}`}
          htmlFor="file-in"
          data-testid="drop"
          style={{ borderRadius: files.length ? "var(--r-lg) var(--r-lg) 0 0" : "var(--r-lg)", margin: 0 }}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
        >
          <Icon name="upload" />
          <b>גררו לכאן קבצים, או לחצו לבחירה</b>
          <span className="small muted">
            {`שרטוט, תוכנית מתכנן או כתב כמויות (גם צילום של כתב יד) · עד 20MB ועד ${maxPages} עמודים לקובץ`}
          </span>
          <input
            id="file-in"
            className="visually-hidden"
            type="file"
            multiple
            onChange={(e) => {
              add(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
        {files.length > 0 && (
          <div aria-label="הקבצים שנבחרו" role="list">
            {files.map((f) => (
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
                  <span className="small muted">
                    {sizeText(f.file.size)}
                    {f.pages ? ` · ${f.pages} עמודים` : ""}
                  </span>
                  {f.error && <div className="err-msg">{f.error.message}</div>}
                </span>
                <span className={`chip ${f.error ? "bad" : "ok"}`}>{f.error ? "נדחה" : "תקין"}</span>
                <button
                  type="button"
                  className="btn ghost sm"
                  data-testid="rmfile"
                  aria-label={`הסר את ${f.file.name}`}
                  onClick={() => setFiles(files.filter((x) => x.key !== f.key))}
                >
                  <Icon name="x" />
                </button>
              </div>
            ))}
            <div className="startbar">
              <span
                className={`small ${start.isError ? "err-msg" : "muted"}`}
                style={{ flex: 1, minWidth: 200 }}
                data-testid="start-note"
              >
                {start.text}
              </span>
              <button type="button" className="btn ghost sm" data-testid="clearfiles" onClick={() => setFiles([])}>
                נקה הכול
              </button>
              <button
                type="button"
                className="btn primary"
                data-testid="start"
                disabled={!start.canStart}
                onClick={() => void begin()}
              >
                התחל פענוח
              </button>
            </div>
          </div>
        )}
      </section>

      {me.flags.chat_quote_builder && !rev && (
        <Link className="card pad row" to="/build" style={{ textDecoration: "none", color: "inherit" }}>
          <span className="kind-ico">
            <Icon name="chat" />
          </span>
          <span style={{ flex: 1, minWidth: 200 }}>
            <b>בלי שרטוט? בנו את ההצעה בצ&apos;אט</b>
            <br />
            <span className="small muted">מתארים את הלוח במילים, והמערכת בונה שורות ומתמחרת מהמחירון</span>
          </span>
          <span className="btn sm">התחל</span>
        </Link>
      )}
    </>
  );
}

function dayMonth(iso: string): string {
  const d = new Date(iso);
  return `${d.getDate()}.${d.getMonth() + 1}`;
}

function RunStep({ progress: p, onCancelled }: { progress: Progress; onCancelled: () => void }) {
  const queries = useQueryClient();
  const toast = useToast();
  const [cancelling, setCancelling] = useState(false);
  const rows = stageRows(p);
  const fileName = p.files[0]?.name ?? p.name;

  async function cancel() {
    setCancelling(true);
    try {
      await cancelDrawing(p.drawing_id);
      void queries.invalidateQueries({ queryKey: ["me"] });
      toast("הפענוח בוטל. המקום במכסה שוחרר");
      onCancelled();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
      void queries.invalidateQueries({ queryKey: ["progress", p.drawing_id] });
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="card pad" style={{ display: "grid", gap: 14 }} data-testid="run">
      <div className="row">
        <h2 className="wrap-any" style={{ flex: 1, minWidth: 0 }}>
          מפענח את <span className="mono">{fileName}</span>
        </h2>
        <span className="small muted num">{`שלב ${stageCounter(p)} מתוך 7`}</span>
      </div>
      <div
        className="meter"
        role="progressbar"
        aria-label="התקדמות הפענוח"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(p.progress * 100)}
      >
        <i style={{ width: `${Math.round(p.progress * 100)}%` }} />
      </div>
      <ol className="stages" style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {rows.map((r) => (
          <li
            key={r.stage}
            className={`stage ${r.state === "done" ? "done" : r.state === "run" ? "run" : ""}`}
            data-testid={`stage-${r.stage}`}
            data-state={r.state}
          >
            <span className="dot" aria-hidden="true">
              {r.state === "done" ? "✓" : r.stage}
            </span>
            <span style={{ minWidth: 0 }}>
              <b>{r.name}</b>
              {r.state === "done" && r.summary && (
                <>
                  <br />
                  <span className="small muted">{r.summary}</span>
                </>
              )}
            </span>
            <span className="st">
              {r.state === "done" ? (
                "הושלם"
              ) : r.state === "run" ? (
                <>
                  <span className="spin" aria-hidden="true" />
                  עובד
                </>
              ) : (
                <span className="visually-hidden">ממתין</span>
              )}
            </span>
          </li>
        ))}
      </ol>
      <div className="row">
        <span className="small muted" style={{ flex: 1, minWidth: 200 }}>
          {p.counted_as === "revision"
            ? "גרסה חדשה: לא נספרת במכסה."
            : "שמרנו לכם מקום אחד במכסה. אם הפענוח ייכשל או יבוטל, הוא משתחרר."}{" "}
          אפשר לסגור את המסך, וההצעה תחכה ברשימה.
        </span>
        <button
          type="button"
          className="btn ghost sm danger"
          data-testid="cancelrun"
          disabled={cancelling}
          onClick={() => void cancel()}
        >
          בטל פענוח
        </button>
      </div>
    </div>
  );
}

function DoneStep({ progress: p, me }: { progress: Progress; me: Me }) {
  const navigate = useNavigate();
  const queries = useQueryClient();
  const refreshed = useRef(false);
  const summary = p.summary;
  useEffect(() => {
    if (refreshed.current) return;
    refreshed.current = true; // the quota, home's recent work and its counts all changed
    for (const key of ["me", "quotes", "home-summary", "revisable"])
      void queries.invalidateQueries({ queryKey: [key] });
  }, [queries]);
  const quota = quotaView(me.quota);
  const [kind, kindNote] = INPUT_KINDS[summary?.input_kind ?? ""] ?? ["—", ""];
  const routes = summary?.pages_by_route ?? {};

  return (
    <div className="card pad" style={{ display: "grid", gap: 14 }} data-testid="done">
      <div className="row">
        <span className="chip ok">הפענוח הסתיים</span>
        <h2 style={{ flex: 1 }}>{p.name}</h2>
      </div>
      {summary && (
        <div className="sumgrid">
          <div>
            <span className="eyebrow">סוג הקלט</span>
            <b>{kind}</b>
            <span className="small muted">{kindNote}</span>
          </div>
          <div>
            <span className="eyebrow">לוחות</span>
            <b className="num">{summary.panels.length}</b>
            <span className="small muted">{summary.panels.join(", ")}</span>
          </div>
          <div>
            <span className="eyebrow">עמודים</span>
            <b className="num">{summary.page_count}</b>
            <span className="small muted">{`${routes.process ?? 0} פענוח · ${routes.context ?? 0} הקשר · ${routes.skip ?? 0} דילוג`}</span>
          </div>
          <div>
            <span className="eyebrow">תוצאה</span>
            <b className="num">{`${summary.products} מוצרים`}</b>
            <span className="small muted">{`${summary.priced} עם מחיר · ${summary.findings} ממצאים`}</span>
          </div>
        </div>
      )}
      <Notices progress={p} />
      <div style={{ display: "grid", gap: 4 }}>
        <h3 style={{ margin: 0 }}>סיווג העמודים</h3>
        <span className="small muted">{gridHint(p)}</span>
      </div>
      <PageGrid progress={p} />
      <div className="row">
        <span className="small muted" style={{ flex: 1, minWidth: 200 }}>
          {countedText(p, quota.label)}
        </span>
        <button
          type="button"
          className="btn primary"
          data-testid="toreview"
          disabled={!p.quote_id}
          onClick={() => navigate(`/review/${p.quote_id ?? ""}`)}
        >
          המשך לבדיקה
        </button>
      </div>
    </div>
  );
}

/**
 * The pages wait for the user (01 §5.6; S08 decision: the done step's grid, a line saying why, the unsure pages
 * marked, and "אשר והמשך"). Changing a kind here re-runs nothing: decoding hasn't gone past stage 1.
 */
function ConfirmStep({ progress: p, me, onCancelled }: { progress: Progress; me: Me; onCancelled: () => void }) {
  const queries = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try {
      queries.setQueryData(["progress", p.drawing_id], await confirmDrawing(p.drawing_id));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
      void queries.invalidateQueries({ queryKey: ["progress", p.drawing_id] });
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    try {
      await cancelDrawing(p.drawing_id);
      void queries.invalidateQueries({ queryKey: ["me"] });
      toast("הפענוח בוטל. המקום במכסה שוחרר");
      onCancelled();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
    } finally {
      setBusy(false);
    }
  }

  const reasons = p.confirmation_reasons.map((r) => CONFIRM_REASONS[r]).filter(Boolean);
  const mapping = Boolean(me.flags.bom_column_mapping) && bomPages(p).length > 0;
  const problem = mapping ? bomProblem(p) : null;
  return (
    <div className="card pad" style={{ display: "grid", gap: 14 }} data-testid="confirm-pages">
      <div className="row">
        <span className="chip warn">ממתין לאישור</span>
        <h2 className="wrap-any" style={{ flex: 1, minWidth: 0 }}>
          {p.name}
        </h2>
      </div>
      <div style={{ display: "grid", gap: 4 }}>
        <h3 style={{ margin: 0 }}>בדקו את סיווג העמודים</h3>
        <span className="small muted" data-testid="confirm-reasons">
          {reasons.length ? reasons.join(" ") : "הסיווג תוקן. אשרו כדי להמשיך בפענוח."}
        </span>
      </div>
      <Notices progress={p} />
      <PageGrid progress={p} />
      {mapping && <BomMapping progress={p} />}
      <div className="row">
        <span
          className={`small ${problem ? "warn-msg" : "muted"}`}
          style={{ flex: 1, minWidth: 200 }}
          data-testid="confirm-note"
        >
          {problem ?? "הפענוח ימשיך אחרי האישור. אפשר לסגור את המסך, וההצעה תחכה ברשימה."}
        </span>
        <button type="button" className="btn ghost sm danger" disabled={busy} onClick={() => void cancel()}>
          בטל פענוח
        </button>
        <button
          type="button"
          className="btn primary"
          data-testid="confirm"
          disabled={busy || problem !== null}
          onClick={() => void confirm()}
        >
          אשר והמשך
        </button>
      </div>
    </div>
  );
}

/**
 * A BOM spreadsheet's columns and their roles (01 §5.8; S14 decision 1, behind `bom_column_mapping`): the header,
 * the first cells below it, and a role the user can change. Not in the prototype: built in the confirmation
 * step's style. A role the model suggested is marked for checking; "אשר והמשך" waits for one item and one quantity.
 */
function BomMapping({ progress: p }: { progress: Progress }) {
  const queries = useQueryClient();
  const toast = useToast();
  const [saving, setSaving] = useState(false);

  async function change(pageId: string, index: number, role: BomRole) {
    setSaving(true);
    try {
      queries.setQueryData(["progress", p.drawing_id], await setBomColumns(p.drawing_id, pageId, [{ index, role }]));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
      void queries.invalidateQueries({ queryKey: ["progress", p.drawing_id] });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 10 }} data-testid="bom-mapping">
      {bomPages(p).map((page) => {
        const bom = page.bom;
        if (!bom) return null;
        const title = bom.sheet ? `עמודות כתב הכמויות · ${bom.sheet}` : "עמודות כתב הכמויות";
        return (
          <section key={page.page_id} style={{ display: "grid", gap: 6 }} aria-label={title}>
            <div className="row">
              <h3 style={{ margin: 0, flex: 1 }}>{title}</h3>
              <span className="small muted">{countText(bom.rows, "שורה אחת", (n) => `${n} שורות`)}</span>
            </div>
            <div className="tbl-wrap card">
              <table className="tbl bommap">
                <thead>
                  <tr>
                    <th>עמודה</th>
                    <th>כותרת</th>
                    <th>דוגמאות</th>
                    <th>תפקיד</th>
                  </tr>
                </thead>
                <tbody>
                  {bom.columns.map((c) => {
                    const by = BOM_BY[c.by] ?? BOM_BY.code;
                    return (
                      <tr key={c.index}>
                        <td className="mono" dir="ltr">
                          {c.letter}
                        </td>
                        <td>
                          {c.header ?? <span className="muted">—</span>}
                          <Samples samples={c.samples} inline />
                        </td>
                        <td className="samples">
                          <Samples samples={c.samples} />
                        </td>
                        <td>
                          <div className="row bomrole">
                            <select
                              className="input"
                              aria-label={`תפקיד עמודה ${c.letter}`}
                              value={c.role}
                              disabled={saving}
                              onChange={(e) => void change(page.page_id, c.index, e.target.value as BomRole)}
                            >
                              {Object.entries(BOM_ROLES).map(([value, label]) => (
                                <option key={value} value={value}>
                                  {label}
                                </option>
                              ))}
                            </select>
                            <span className={`chip ${by?.chip ?? ""}`}>{by?.label}</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
    </div>
  );
}

/** A column's first cells, each kept in its own direction ("מגען 3X25", "120.50"), so they don't run together. */
function Samples({ samples, inline = false }: { samples: string[]; inline?: boolean }) {
  return (
    <span className={inline ? "samples-inline" : undefined}>
      {samples.length
        ? samples.map((x, i) => (
            <Fragment key={i}>
              {i > 0 && " · "}
              <bdi>{x}</bdi>
            </Fragment>
          ))
        : "—"}
    </span>
  );
}

/** Stage 1's notices for the user (01 §8): low resolution, a drawing marked "לעיון", a version counted as new. */
function Notices({ progress: p }: { progress: Progress }) {
  if (!p.notices.length) return null;
  return (
    <ul className="small" style={{ margin: 0, paddingInlineStart: 18 }} data-testid="notices">
      {p.notices.map((n, i) => (
        <li key={`${n.code}-${i}`} className={n.severity === "warning" ? "warn-msg" : "muted"}>
          {n.message}
        </li>
      ))}
    </ul>
  );
}

/**
 * A card per page (prototype lines 847–852): picture, number, route, kind, and a short note. The kind can be
 * changed (01 §5.6). On a finished drawing a change of route runs decoding again from stage 2.
 */
function PageGrid({ progress: p }: { progress: Progress }) {
  const queries = useQueryClient();
  const toast = useToast();
  const [saving, setSaving] = useState<string | null>(null);

  async function change(pageId: string, kind: PageKind) {
    setSaving(pageId);
    try {
      const next = await changePageKind(p.drawing_id, pageId, kind);
      queries.setQueryData(["progress", p.drawing_id], next);
      toast(next.status === "processing" ? "סוג העמוד עודכן. הפענוח רץ שוב משלב 2" : "סוג העמוד עודכן");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : FALLBACK);
      void queries.invalidateQueries({ queryKey: ["progress", p.drawing_id] });
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="thumbs">
      {p.pages.map((page) => {
        const route = ROUTES[page.route ?? "process"] ?? ROUTES.process;
        return (
          <div
            className={`thumb${page.unsure ? " unsure" : ""}`}
            key={page.page_id}
            data-testid="thumb"
            data-unsure={page.unsure ? "true" : undefined}
          >
            {page.thumbnail_url ? (
              <img src={page.thumbnail_url} alt={`עמוד ${page.page_no}`} />
            ) : (
              <div className="thumb-ph" role="img" aria-label={`עמוד ${page.page_no}, בלי תמונה`}>
                {page.bom?.source === "spreadsheet" ? "גיליון, בלי תמונה" : "בלי תמונה"}
              </div>
            )}
            <div className="row small">
              <b>{`עמוד ${page.page_no}`}</b>
              <span className="spacer" />
              <span className={`chip ${route?.chip ?? ""}`}>{route?.label}</span>
            </div>
            <select
              className="input"
              aria-label={`סוג עמוד ${page.page_no}`}
              value={page.page_kind ?? "other"}
              disabled={saving !== null}
              onChange={(e) => void change(page.page_id, e.target.value as PageKind)}
            >
              {Object.entries(PAGE_KINDS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <span className="tnote">{pageNote(page)}</span>
          </div>
        );
      })}
    </div>
  );
}

function FailedStep({ progress: p, onBack }: { progress: Progress; onBack: () => void }) {
  return (
    <div className="card pad" style={{ display: "grid", gap: 14 }} data-testid="failed">
      <div className="row">
        <span className="chip bad">הפענוח נכשל</span>
        <h2 className="wrap-any" style={{ flex: 1, minWidth: 0 }}>
          {p.name}
        </h2>
      </div>
      <p className="err-msg" role="alert" style={{ margin: 0 }}>
        {p.error ?? FALLBACK}
      </p>
      <div className="row">
        <span className="spacer" />
        <button type="button" className="btn primary" onClick={onBack}>
          העלאה מחדש
        </button>
      </div>
    </div>
  );
}
