import type { Quota } from "../api/client";

/**
 * What the quota looks like on screen (01 §4.5). The server decides the state (`quota_near` is strictly above
 * 80%, `quota_reached` is at the limit); this only turns it into text, a meter width and a banner.
 * Reserved uploads count as taken, the same as the server's check.
 */
export interface QuotaView {
  /** "12 מתוך 50", or "12 הצעות" for an unlimited plan. */
  label: string;
  /** Meter width in percent, 0–100. Null when there is no limit to measure against. */
  pct: number | null;
  tone: "ok" | "warn" | "full";
  /** "New quote" is blocked. Existing quotes stay fully available. */
  blocked: boolean;
  remaining: number | null;
  /** The top banner, shown above 80% and at 100%. */
  banner: string | null;
  /** "1.11": the first day of next month, when the counter starts again. */
  renews: string;
}

export const FULL_BANNER =
  "הגעתם למכסת ההצעות של החודש. אפשר להמשיך לעבוד על ההצעות הקיימות. להגדלת החבילה פנו לצוות קונבורו";

export function remainingText(remaining: number): string {
  return remaining === 1 ? "נותרה הצעה אחת החודש" : `נותרו ${remaining} הצעות החודש`;
}

function renewsOn(month: string): string {
  const [, m] = month.split("-").map(Number);
  return `1.${((m ?? 12) % 12) + 1}`;
}

export function quotaView(quota: Quota): QuotaView {
  const counter = quota.counters.find((c) => c.counter === "quote");
  const renews = renewsOn(quota.month);
  if (!counter || counter.limit === null) {
    const taken = counter ? counter.used + counter.reserved : 0;
    return { label: `${taken} הצעות`, pct: null, tone: "ok", blocked: false, remaining: null, banner: null, renews };
  }
  const capacity = counter.limit + counter.extra;
  const taken = counter.used + counter.reserved;
  const pct = capacity > 0 ? Math.min(100, Math.round((100 * taken) / capacity)) : 100;
  const remaining = counter.remaining ?? Math.max(0, capacity - taken);
  const label = `${taken} מתוך ${capacity}`;
  if (counter.state === "quota_reached") {
    return { label, pct, tone: "full", blocked: true, remaining: 0, banner: FULL_BANNER, renews };
  }
  if (counter.state === "quota_near") {
    return { label, pct, tone: "warn", blocked: false, remaining, banner: remainingText(remaining), renews };
  }
  return { label, pct, tone: "ok", blocked: false, remaining, banner: null, renews };
}
