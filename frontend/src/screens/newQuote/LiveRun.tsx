import { useEffect, useState } from "react";

import type { Live, Progress } from "../../api/client";
import { Icon } from "../../ui/Icon";
import { setNotify, useWatchedRun } from "../../shell/runWatch";
import {
  boxStyle,
  counterItems,
  leftText,
  liveSentence,
  mmss,
  modelsText,
  STAGE_ICONS,
  stageMessage,
  stagesTitle,
  stepText,
  usd,
} from "./live";
import { stageRows } from "./model";

const BLOCKED = "הדפדפן חוסם התראות. נודיע כאן, בכל מסך שתהיו בו";

/** Seconds since the data came, ticking every second: the clock moves between the two-second polls. */
function useTick(updatedAt: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return Math.max(0, Math.floor((now - updatedAt) / 1000));
}

/**
 * The live run step (01 §4.6 "ריצה", prototype `vNew` run phase and `updateRun`, lines 922–950 and 991–1034),
 * behind `live_run`: the header's live sentence, the meter by expected time, time, progress and cost, what the
 * system sees now, the log, the stages with their icons, and "הודע לי". On a phone the page view and the log are
 * hidden (CSS, under 860px).
 */
export function LiveRunStep(props: {
  progress: Progress;
  live: Live;
  updatedAt: number;
  cancelling: boolean;
  onCancel: () => void;
}) {
  const { progress: p, live } = props;
  const delta = useTick(props.updatedAt);
  const elapsed = live.elapsed_s + (live.started_at ? delta : 0);
  const pct = Math.min(99, Math.round(100 * live.fraction));
  const fileName = p.files[0]?.name ?? p.name;
  const sentence = liveSentence(p);

  return (
    <div className="run-live" data-testid="run">
      <div className="card pad" style={{ display: "grid", gap: 14 }}>
        <div className="run-head">
          <span className="orb" aria-hidden="true">
            <Icon name="ai" />
          </span>
          <div style={{ flex: 1, minWidth: 180 }}>
            <h2 className="wrap-any" style={{ margin: 0 }}>
              המערכת מפענחת את <span className="mono">{fileName}</span>
            </h2>
            <span className="small muted" aria-live="polite" data-testid="run-sub">
              {sentence}
            </span>
          </div>
          <button
            type="button"
            className="btn ghost sm danger"
            data-testid="cancelrun"
            disabled={props.cancelling}
            onClick={props.onCancel}
          >
            בטל פענוח
          </button>
        </div>
        <div
          className="meter ai"
          role="progressbar"
          aria-label="התקדמות הפענוח"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
        >
          <i style={{ width: `${pct}%` }} />
        </div>
        <div className="run-kpis">
          <div>
            <span className="eyebrow">
              <Icon name="clock" /> זמן
            </span>
            <b className="num" dir="ltr" data-testid="run-clock">
              {mmss(elapsed)}
            </b>
            <span className="small muted" data-testid="run-eta">
              {leftText(live)}
            </span>
          </div>
          <div>
            <span className="eyebrow">התקדמות</span>
            <b className="num" dir="ltr" data-testid="run-pct">{`${pct}%`}</b>
            <span className="small muted">{stepText(p)}</span>
          </div>
          <div>
            <span className="eyebrow">עלות עד עכשיו</span>
            <b className="num" dir="ltr" data-testid="run-cost">
              {usd(live.cost_usd)}
            </b>
            <span className="small muted">
              צפוי כ-
              <span className="num" dir="ltr">
                {usd(live.cost_estimate_usd)}
              </span>
            </span>
          </div>
        </div>
      </div>
      <div className="run-grid">
        <section className="card pad" style={{ display: "grid", gap: 10 }} aria-label="מה המערכת רואה">
          <h3 style={{ margin: 0 }}>מה המערכת רואה עכשיו</h3>
          <PageView progress={p} live={live} elapsed={elapsed} />
          <div className="counters" data-testid="run-counters">
            {counterItems(
              live.counters,
              p.files.reduce((n, f) => n + (f.page_count ?? 0), 0),
            ).map((c) => (
              <span key={c.label}>
                {c.label}{" "}
                <b className="num" dir="ltr">
                  {c.value}
                </b>
              </span>
            ))}
          </div>
          <div className="run-log" data-testid="run-log">
            <span className="eyebrow">יומן</span>
            <div className="feed" aria-live="off">
              {[...live.messages].reverse().map((m) => (
                <div key={`${m.at_s}-${m.stage}-${m.text}`}>
                  <span className="num" dir="ltr">
                    {mmss(m.at_s)}
                  </span>
                  <span>{m.text}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
        <section className="card pad" style={{ display: "grid", gap: 10 }} aria-label="שלבי הפענוח">
          <h3 style={{ margin: 0 }}>{stagesTitle(p.stages.length)}</h3>
          <LiveStages progress={p} live={live} delta={delta} />
          <div className="row small" style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
            <span className="muted" style={{ flex: 1, minWidth: 200 }}>
              {p.counted_as === "revision"
                ? "גרסה חדשה: לא נספרת במכסה."
                : "שמרנו מקום אחד במכסה. אם הפענוח ייכשל או יבוטל, הוא משתחרר."}{" "}
              אפשר לעבור למסך אחר, והפענוח ימשיך.
            </span>
            <NotifySwitch drawingId={p.drawing_id} />
          </div>
        </section>
      </div>
    </div>
  );
}

function LiveStages({ progress: p, live, delta }: { progress: Progress; live: Live; delta: number }) {
  const times = new Map(live.stages.map((s) => [s.stage, s]));
  return (
    <ol className="stages live-stages" style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {stageRows(p).map((r) => {
        const t = times.get(r.stage);
        const running = r.state === "run";
        const seconds = t?.seconds != null ? t.seconds + (running ? delta : 0) : null;
        const cost = t?.cost_usd != null && Number(t.cost_usd) > 0 ? t.cost_usd : null;
        return (
          <li
            key={r.stage}
            className={`stage ${r.state === "done" ? "done" : running ? "run" : r.state === "failed" ? "failed" : ""}`}
            data-testid={`stage-${r.stage}`}
            data-state={r.state}
          >
            <span className="sico" aria-hidden="true">
              {r.state === "done" ? "✓" : <Icon name={STAGE_ICONS[r.stage] ?? "ai"} />}
            </span>
            <span style={{ minWidth: 0 }}>
              <b>{r.name}</b>
              <br />
              {r.state === "done" ? (
                <span className="small muted">{r.summary}</span>
              ) : running ? (
                <span className="live">{stageMessage(p, r.stage) ?? "עובד"}</span>
              ) : (
                <span className="small muted">{r.state === "failed" ? "נכשל" : "ממתין"}</span>
              )}
            </span>
            <span className="st">
              {seconds !== null && (
                <span className="num" dir="ltr">
                  {mmss(seconds)}
                </span>
              )}
              {cost && (
                <span className="num" dir="ltr">
                  {usd(cost)}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The page the run is on, with the scan line; stage 2 fills the tiles, stage 3 draws its boxes (01 §4.6). */
function PageView({ progress: p, live, elapsed }: { progress: Progress; live: Live; elapsed: number }) {
  const view = live.view;
  const stage = p.stages.find((s) => s.status === "running")?.stage ?? null;
  const pages = live.counters.pages ?? p.files.reduce((n, f) => n + (f.page_count ?? 0), 0);
  const name = p.stages.find((s) => s.stage === stage)?.name ?? "";
  const [broken, setBroken] = useState<string | null>(null);
  const tilesOn = (elapsed % 12) + 1; // the tiles fill while the text is read, a second each
  return (
    <div className="view" data-testid="run-view">
      {view?.image_url && broken !== view.image_url && (
        <img
          src={view.image_url}
          alt={view.page_no ? `עמוד ${view.page_no}, שמפוענח עכשיו` : "העמוד שמפוענח עכשיו"}
          onError={() => setBroken(view.image_url)}
        />
      )}
      <div className="ovl" aria-hidden="true">
        {stage === 2 && (
          <div className="tiles">
            {Array.from({ length: 12 }, (_, i) => (
              <i key={i} className={i < tilesOn ? "on" : ""} />
            ))}
          </div>
        )}
        {stage !== 2 &&
          view?.size &&
          view.boxes.map((b, i) => <i key={i} className="bx" style={boxStyle(b, view.size ?? [1, 1])} />)}
      </div>
      <span className="scanline" aria-hidden="true" />
      {view?.page_no && (
        <span className="vlabel">{`עמוד ${view.page_no}${pages ? ` מתוך ${pages}` : ""}${name ? ` · ${name}` : ""}`}</span>
      )}
    </div>
  );
}

/** "הודע לי כשמסתיים" (01 §4.6): turning it on asks the browser's permission; a blocked browser gets the in-app
 * notice only, and the switch says so. */
function NotifySwitch({ drawingId }: { drawingId: string }) {
  const run = useWatchedRun();
  const on = run?.drawingId === drawingId && run.notify;
  const [blocked, setBlocked] = useState(
    () => typeof Notification !== "undefined" && Notification.permission === "denied",
  );

  async function toggle() {
    const next = !on;
    setNotify(drawingId, next);
    if (!next || typeof Notification === "undefined") return;
    const permission =
      Notification.permission === "default" ? await Notification.requestPermission() : Notification.permission;
    setBlocked(permission === "denied");
  }

  return (
    <span style={{ display: "grid", gap: 2 }}>
      <label className="notify-switch small">
        <button
          type="button"
          className="toggle"
          role="switch"
          aria-checked={on}
          data-testid="runnotify"
          aria-label="הודע לי כשהפענוח מסתיים"
          onClick={() => void toggle()}
        />
        <Icon name="bell" /> הודע לי כשמסתיים
      </label>
      {on && blocked && (
        <span className="small muted" data-testid="notify-blocked">
          {BLOCKED}
        </span>
      )}
    </span>
  );
}

/** The done step's time and cost tiles (01 §4.6 "סיום", `live_run`). */
export function LiveDoneTiles({ live }: { live: Live }) {
  return (
    <>
      <div data-testid="done-time">
        <span className="eyebrow">זמן פענוח</span>
        <b className="num" dir="ltr">
          {mmss(live.elapsed_s)}
        </b>
        <span className="small muted">
          צפוי היה{" "}
          <span className="num" dir="ltr">
            {mmss(Math.round(live.seconds_expected / 10) * 10)}
          </span>
        </span>
      </div>
      <div data-testid="done-cost">
        <span className="eyebrow">עלות הפענוח</span>
        <b className="num" dir="ltr">
          {usd(live.cost_usd)}
        </b>
        <span className="small muted">
          מודלים וקריאת טקסט ·{" "}
          <span className="num" dir="ltr">
            {usd(live.cost_per_page_usd)}
          </span>{" "}
          לעמוד
        </span>
      </div>
    </>
  );
}

/** "פירוט לפי שלב" (01 §4.6): each stage's time, cost and what ran in it. */
export function LiveBreakdown({ progress: p, live }: { progress: Progress; live: Live }) {
  const times = new Map(live.stages.map((s) => [s.stage, s]));
  return (
    <details data-testid="breakdown">
      <summary className="small" style={{ cursor: "pointer" }}>
        פירוט לפי שלב
      </summary>
      <div className="tbl-wrap" style={{ marginTop: 8 }}>
        <table className="tbl breakdown">
          <thead>
            <tr>
              <th>שלב</th>
              <th>זמן</th>
              <th>עלות</th>
              <th>מה רץ</th>
            </tr>
          </thead>
          <tbody>
            {p.stages.map((s) => {
              const t = times.get(s.stage);
              return (
                <tr key={s.stage}>
                  <td>
                    <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      <Icon name={STAGE_ICONS[s.stage] ?? "ai"} />
                      {s.name}
                    </span>
                  </td>
                  <td className="n">
                    <span className="num" dir="ltr">
                      {t?.seconds != null ? mmss(t.seconds) : "—"}
                    </span>
                  </td>
                  <td className="n">
                    <span className="num" dir="ltr">
                      {t?.cost_usd != null && Number(t.cost_usd) > 0 ? usd(t.cost_usd) : "—"}
                    </span>
                  </td>
                  <td className="small muted">{modelsText(t?.models ?? [], s.stage)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <span className="small muted">
        העלות בפועל, בדולרים: טוקנים לפי מחירון הספק, כולל ניסיונות חוזרים, ועמודי קריאת טקסט. בלי צ&apos;אט ובלי פעולות
        במסך הבדיקה.
      </span>
    </details>
  );
}
