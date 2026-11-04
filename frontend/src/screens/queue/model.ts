/** The approval queue's cards (prototype `vQueue`, lines 1210–1226), without React. */

import type { Candidate } from "../../api/client";

export const KIND_LABEL: Record<Candidate["kind"], string> = {
  symbol: "סימן חדש",
  abbreviation: "קיצור",
  spelling: "כתיב",
  catalog_item: "פריט קטלוג",
  catalog_attribute: "תכונת פריט",
};

/** The prototype's toasts (line 1506). */
export const APPROVED_TOAST = "עבר לשכבה המשותפת, עם מקור pilot_engineer";
export const REJECTED_TOAST = "נדחה. נשאר רק אצלכם";

function dayKey(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(iso),
  );
}

/** "היום", or "28.10", in the factory's time zone. */
export function when(iso: string, timeZone: string, now: Date = new Date()): string {
  if (dayKey(iso, timeZone) === dayKey(now.toISOString(), timeZone)) return "היום";
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone, day: "2-digit", month: "2-digit" }).formatToParts(
    new Date(iso),
  );
  const get = (type: string) => parts.find((x) => x.type === type)?.value ?? "";
  return `${get("day")}.${get("month")}`;
}

/** "מקור: תיקון בהצעה, 28.10" (the prototype's `from`). */
export function originText(c: Candidate, timeZone: string, now: Date = new Date()): string {
  const date = when(c.created_at, timeZone, now);
  return c.origin ? `${c.origin}, ${date}` : date;
}
