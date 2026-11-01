import type { Finding, QuoteLine } from "../../api/client";
import { Icon } from "../../ui/Icon";
import { attributeLabel, lineFindings, percent, priceSourceText, shekels, sourceText } from "./model";

/**
 * Line detail, read-only in S09 (S09 decision 7): what the drawing says, where each value comes from, why, the
 * price and its source, cost and margin, the line's findings and its alternatives (09 §6.4, prototype `lineDetail`).
 * Editing arrives in S23. "הצג בשרטוט" frames the line on the drawing (S11), for a line that has an instance.
 */
export function LineDetail(props: {
  line: QuoteLine;
  findings: Finding[];
  onShowOnDrawing?: (line: QuoteLine) => void;
}) {
  const { line, findings, onShowOnDrawing } = props;
  const own = lineFindings(line, findings);
  return (
    <div className="detail" data-testid="line-detail" id={`detail-${line.line_id}`}>
      <div className="dgrid">
        <div style={{ display: "grid", gap: 8 }}>
          <span className="eyebrow">מה כתוב בשרטוט</span>
          {line.raw_text.length ? (
            <div className="raw">{line.raw_text.join("\n")}</div>
          ) : (
            <span className="small muted">אין טקסט בשרטוט לשורה הזו</span>
          )}
          {line.explanation ? <div className="small why">{line.explanation}</div> : null}
          {line.derived ? (
            <div className="small">
              <span className="muted">איך חושב: </span>
              {line.derived.explanation}
            </div>
          ) : null}
        </div>
        <div style={{ display: "grid", gap: 8, alignContent: "start" }}>
          <span className="eyebrow">מאיפה כל ערך</span>
          {line.sources.length ? (
            <dl className="kv">
              {line.sources.map((s) => {
                const src = sourceText(s);
                return <SourceRow key={s.attribute} label={attributeLabel(s.attribute)} value={s.value} {...src} />;
              })}
            </dl>
          ) : (
            <span className="small muted">אין תכונות שנקראו</span>
          )}
          {line.sku ? (
            <span className="small muted">
              מק"ט יצרן: <span className="mono">{line.sku}</span>
            </span>
          ) : null}
        </div>
      </div>
      <div className="dgrid">
        <div style={{ display: "grid", gap: 6, alignContent: "start" }}>
          <span className="eyebrow">מחיר</span>
          <PriceBox line={line} />
        </div>
        {line.included ? null : (
          <div style={{ display: "grid", gap: 6, alignContent: "start" }}>
            <span className="eyebrow">עלות ורווח</span>
            <CostBox line={line} />
          </div>
        )}
      </div>
      {own.length ? (
        <div style={{ display: "grid", gap: 6 }}>
          <span className="eyebrow">ממצאי הבודק</span>
          {own.map((f) => (
            <div key={f.finding_id} className="row small" style={{ alignItems: "stretch" }}>
              <span className={`sev ${f.severity}`} aria-hidden="true" />
              <span>
                <b>{f.title ?? f.message}</b>
                {f.title ? <span className="muted"> · {f.message}</span> : null}
              </span>
            </div>
          ))}
        </div>
      ) : null}
      <div style={{ display: "grid", gap: 6 }}>
        <span className="eyebrow">חלופות</span>
        {line.alternatives.length ? (
          line.alternatives.map((alt) => (
            <div key={alt.description} className="alt">
              <span style={{ flex: 1 }}>{alt.description}</span>
            </div>
          ))
        ) : (
          <span className="small muted">אין חלופות. הדגם כתוב בשרטוט</span>
        )}
      </div>
      {onShowOnDrawing && line.boxes.length ? (
        <div className="row">
          <button type="button" className="btn sm" data-testid="showdraw" onClick={() => onShowOnDrawing(line)}>
            <Icon name="eye" />
            הצג בשרטוט
          </button>
        </div>
      ) : null}
    </div>
  );
}

function SourceRow(props: { label: string; value: string | null; text: string; warn: boolean }) {
  return (
    <>
      <dt>{props.label}</dt>
      <dd>
        <b>{props.value ?? "—"}</b>
      </dd>
      <dd className={`small ${props.warn ? "warn-t" : "muted"}`}>{props.text}</dd>
    </>
  );
}

function PriceBox({ line }: { line: QuoteLine }) {
  if (line.included) return <span className="small muted">כלול במחיר שורת האב (ערכה)</span>;
  if (line.unit_price == null) return <span className="small">אין מחיר זהה במחירון. הזנת מחיר מהשורה תגיע בהמשך</span>;
  return (
    <>
      <dl className="kv">
        <dt>מחיר מכירה ליחידה</dt>
        <dd className="num">
          <b>{shekels(line.unit_price)}</b>
        </dd>
        <dd />
      </dl>
      <span className="small muted">מקור: {priceSourceText(line)}</span>
    </>
  );
}

function CostBox({ line }: { line: QuoteLine }) {
  if (line.unit_cost == null) return <span className="small muted">אין עלות למוצר הזה, ולכן אין חישוב רווח.</span>;
  return (
    <dl className="kv">
      <dt>עלות ליחידה</dt>
      <dd className="num">
        <b>{shekels(line.unit_cost)}</b>
      </dd>
      <dd className="small muted">{line.cost_source?.supplier ?? ""}</dd>
      {line.unit_margin != null ? (
        <>
          <dt>רווח ליחידה</dt>
          <dd className="num">
            <b>{shekels(line.unit_margin)}</b>
          </dd>
          <dd className="small muted">{percent(line.margin_pct)}</dd>
        </>
      ) : null}
    </dl>
  );
}
