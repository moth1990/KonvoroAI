/** The two questions of 10 §5.1, without React: what the markup text means, and the live example under it. */

export type Family = "circuit_breaker" | "rcd";
export type Brand = "Schneider" | "ABB" | "Hager" | "other";

export const FAMILIES: { key: Family; label: string }[] = [
  { key: "circuit_breaker", label: "מא״זים" },
  { key: "rcd", label: "מפסקי פחת" },
];

/** The question's options, in its order; "אחר" sets no preference (S24 decision 7). */
export const BRANDS: { value: Brand; label: string }[] = [
  { value: "Schneider", label: "שניידר" },
  { value: "ABB", label: "ABB" },
  { value: "Hager", label: "האגר" },
  { value: "other", label: "אחר" },
];

export const DEFAULT_MARKUP = "25";
const PERCENT = /^\d{1,3}(\.\d{1,2})?$/;
const MAX_UNITS = 50_000; // 500%, in hundredths of a percent: above it is a typing mistake (the server agrees)

/** Hundredths of a percent: "25" → 2500, "12.5" → 1250. Null for anything that is not a percent up to 500. */
function units(text: string): number | null {
  const t = text.trim();
  if (!PERCENT.test(t)) return null;
  const [whole = "0", frac = ""] = t.split(".");
  const u = Number(whole) * 100 + Number((frac + "00").slice(0, 2));
  return u <= MAX_UNITS ? u : null;
}

/** "25" → "0.25", "12.5" → "0.125": the markup as the API takes it, a rate in a string (never a float). */
export function markupRate(text: string): string | null {
  const u = units(text);
  if (u === null) return null;
  const s = u.toString().padStart(5, "0");
  return `${s.slice(0, -4)}.${s.slice(-4)}`.replace(/0+$/, "").replace(/\.$/, "");
}

/** "0.2500" → "25", "0.125" → "12.5": a rate from the API shown as the percent the user typed. */
export function ratePercentText(rate: string): string {
  const [whole = "0", frac = ""] = rate.split(".");
  const u = Number(whole) * 10_000 + Number((frac + "0000").slice(0, 4));
  const s = u.toString().padStart(3, "0");
  return `${s.slice(0, -2)}.${s.slice(-2)}`.replace(/\.?0+$/, "") || "0";
}

/** The question's example, updated on every key: "עלות ₪100 ← מחיר ללקוח ₪125". Null while the text is not valid. */
export function examplePrice(text: string): string | null {
  const u = units(text);
  if (u === null) return null;
  const hundredths = 10_000 + u; // ₪100 plus the markup, in agorot
  const shekels = Math.floor(hundredths / 100);
  const agorot = hundredths % 100;
  return agorot ? `₪${shekels}.${agorot.toString().padStart(2, "0")}` : `₪${shekels}`;
}
