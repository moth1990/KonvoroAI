import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  fetchCustomerDocument,
  fetchExport,
  fetchVersions,
  type ExportKind,
  type Quote,
} from "../../api/client";
import { Icon } from "../../ui/Icon";
import { Modal } from "../../ui/Modal";
import { useToast } from "../../ui/Toast";
import { documentRows, exportFileName, quantityText, unpricedText, versionLabel } from "./exportModel";
import { shekels } from "./model";

/**
 * "הורדת ההצעה" (13 §4.1, prototype `exportModal`, lines 1360–1378; S26), behind `export_doc`: the customer
 * document's preview as the PDF prints it (no cost, margin or colour, 07 §12), the unpriced lines' warning, and the two
 * downloads. A quote with more than one version gets a selector, the current one first (S26 decision 2); a draft's
 * preview says "טיוטה", as its PDF does (decision 3).
 */
export function ExportModal({ quote, onClose }: { quote: Quote; onClose: () => void }) {
  const toast = useToast();
  const [version, setVersion] = useState(quote.version);
  const [busy, setBusy] = useState<ExportKind | null>(null);
  const versions = useQuery({
    queryKey: ["versions", quote.quote_id, quote.version, quote.status],
    queryFn: () => fetchVersions(quote.quote_id),
  });
  const doc = useQuery({
    queryKey: ["customer-document", quote.quote_id, version, version === quote.version ? quote.revision : 0],
    queryFn: () => fetchCustomerDocument(quote.quote_id, version),
    placeholderData: (previous) => previous,
  });
  const d = doc.data;

  const download = async (kind: ExportKind) => {
    setBusy(kind);
    try {
      const { blob, name } = await fetchExport(quote.quote_id, version, kind);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name ?? exportFileName(quote.name, version, kind);
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "לא הצלחנו להכין את הקובץ. נסו שוב");
    } finally {
      setBusy(null);
    }
  };

  const several = (versions.data?.length ?? 0) > 1;
  const rows = d ? documentRows(d) : [];
  return (
    <Modal onClose={onClose} labelledBy="export-title" className="wide">
      <div className="row">
        <h2 id="export-title">הורדת ההצעה</h2>
        <span className="v2">דגל</span>
        <span className="spacer" />
        {several ? (
          <select
            className="input"
            style={{ width: "auto" }}
            aria-label="גרסה"
            data-testid="export-version"
            value={version}
            onChange={(e) => setVersion(Number(e.target.value))}
          >
            {versions.data?.map((v) => (
              <option key={v.version} value={v.version}>
                {versionLabel(v)}
              </option>
            ))}
          </select>
        ) : (
          <span className="small muted">גרסה {version}</span>
        )}
      </div>
      <div className="doc" aria-label="תצוגה מקדימה של המסמך ללקוח" data-testid="export-doc" aria-busy={doc.isFetching}>
        {d ? (
          <>
            <div className="row">
              <b style={{ fontSize: 15 }}>הצעת מחיר</b>
              {d.draft ? <span className="doc-draft">טיוטה</span> : null}
              <span className="spacer" />
              <span>
                לוח {d.name}
                {d.drawing_number ? (
                  <>
                    {" · "}
                    <span className="mono">{d.drawing_number}</span>
                  </>
                ) : null}
              </span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>תיאור</th>
                  {d.show_sku ? <th>מק"ט</th> : null}
                  <th className="n">כמות</th>
                  <th className="n">מחיר</th>
                  <th className="n">סה"כ</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) =>
                  r.kind === "panel" ? (
                    <tr key={r.key} className="doc-panel">
                      <td colSpan={d.show_sku ? 5 : 4}>{r.name}</td>
                    </tr>
                  ) : (
                    <tr key={r.key} data-testid="export-row">
                      <td>{r.row.description}</td>
                      {d.show_sku ? <td className="mono">{r.row.sku ?? ""}</td> : null}
                      <td className="n num">{quantityText(r.row.qty)}</td>
                      <td className="n num">{r.row.unit_price == null ? "" : shekels(r.row.unit_price)}</td>
                      <td className="n num">{r.row.line_total == null ? "" : shekels(r.row.line_total)}</td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
            <div style={{ textAlign: "end" }}>
              {d.totals.discount ? (
                <>
                  הנחה <span className="num">{shekels(d.totals.discount)}</span>
                  {" · "}
                </>
              ) : null}
              סה"כ <span className="num">{shekels(d.totals.net_total)}</span> · מע"מ{" "}
              <span className="num">{shekels(d.totals.vat)}</span> ·{" "}
              <b>
                לתשלום <span className="num">{shekels(d.totals.gross_total)}</span>
              </b>
            </div>
          </>
        ) : doc.isError ? (
          <span className="err-msg" role="alert">
            לא הצלחנו לטעון את המסמך. נסו שוב
          </span>
        ) : (
          <span className="small muted">טוען…</span>
        )}
      </div>
      {d && d.unpriced_count ? (
        <span className="small" style={{ color: "var(--bad)" }} role="note" data-testid="export-unpriced">
          {unpricedText(d.unpriced_count)}
        </span>
      ) : null}
      <span className="small muted">
        ה-PDF ללקוח: תיאור, כמות, מחיר וסכום, בלי עלות, רווח וצבעים. ה-Excel לעבודה פנימית: כולל עלות, מקור המחיר וצבע
        השורה.
      </span>
      <div className="row">
        <button
          type="button"
          className="btn primary"
          data-testid="exp-pdf"
          disabled={busy !== null || !d}
          onClick={() => void download("pdf")}
        >
          <Icon name="down" />
          {busy === "pdf" ? "מכין את ה-PDF…" : "PDF ללקוח"}
        </button>
        <button
          type="button"
          className="btn"
          data-testid="exp-xlsx"
          disabled={busy !== null || !d}
          onClick={() => void download("xlsx")}
        >
          <Icon name="down" />
          {busy === "xlsx" ? "מכין את ה-Excel…" : "Excel פנימי"}
        </button>
        <span className="spacer" />
        <button type="button" className="btn ghost" onClick={onClose}>
          סגור
        </button>
      </div>
    </Modal>
  );
}
