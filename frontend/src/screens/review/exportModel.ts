/**
 * The export modal's logic (13 §4.1, prototype `exportModal`; S26), kept apart from React so Vitest can test it.
 */
import type { CustomerDocument, ExportKind, QuoteVersion } from "../../api/client";
import { countText } from "../../format";
import { qtyText } from "./model";

type DocRow = CustomerDocument["sections"][number]["rows"][number];

export type PreviewRow = { kind: "panel"; key: string; name: string } | { kind: "row"; key: string; row: DocRow };

/** The preview's rows: a heading per panel when the quote has several (the PDF's sections), and each row. */
export function documentRows(doc: CustomerDocument): PreviewRow[] {
  const several = doc.sections.length > 1;
  return doc.sections.flatMap((s, i) => [
    ...(several ? [{ kind: "panel" as const, key: `p${i}`, name: s.name }] : []),
    ...s.rows.map((row, j) => ({ kind: "row" as const, key: `${i}:${j}`, row })),
  ]);
}

/** "גרסה 2 · טיוטה", "גרסה 1 · נשלחה". */
export function versionLabel(v: QuoteVersion): string {
  return `גרסה ${v.version} · ${v.status === "sent" ? "נשלחה" : "טיוטה"}`;
}

export const quantityText = qtyText;

/** The prototype's warning before the download (13 §4.1 "שורות בלי מחיר: מופיעות בלי סכום, עם אזהרה"). */
export function unpricedText(n: number): string {
  return countText(n, "שורה אחת בלי מחיר תופיע במסמך בלי סכום.", (k) => `${k} שורות בלי מחיר יופיעו במסמך בלי סכום.`);
}

/** The server names the file; this stands in if a proxy drops the header. */
export function exportFileName(name: string, version: number, kind: ExportKind): string {
  return `${kind === "pdf" ? "הצעת מחיר" : "הצעה פנימית"} ${name} גרסה ${version}.${kind}`;
}
