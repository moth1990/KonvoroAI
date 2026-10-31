/**
 * Display formatting. Money arrives as a decimal string (CLAUDE.md non-negotiable 5) and is formatted as a
 * string: it never goes through a JS number, so no float rounding can creep in.
 */

/** "1250.0000" -> "₪1,250". Whole shekels, cut toward zero: used where the text says "at least". */
export function shekelsFloor(amount: string): string {
  const negative = amount.startsWith("-");
  const whole = (negative ? amount.slice(1) : amount).split(".")[0]?.replace(/^0+(?=\d)/, "") || "0";
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative && whole !== "0" ? "-" : ""}₪${grouped}`;
}

/** Hebrew count phrases: one has its own wording ("מחיר חסר אחד"), the rest use the number. */
export function countText(n: number, one: string, many: (n: number) => string): string {
  return n === 1 ? one : many(n);
}

/** "היום, 09:12", "אתמול", or "28.10" (prototype QUOTES `when`), in the tenant's timezone. */
export function whenText(iso: string, now: Date, timeZone: string): string {
  const day = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone, dateStyle: "short" }).format(d);
  const at = new Date(iso);
  const today = day(now);
  if (day(at) === today) {
    const time = new Intl.DateTimeFormat("he-IL", { timeZone, hour: "2-digit", minute: "2-digit", hour12: false });
    return `היום, ${time.format(at)}`;
  }
  if (day(at) === day(new Date(now.getTime() - 86_400_000))) return "אתמול";
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone, day: "numeric", month: "numeric" }).formatToParts(at);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("day")}.${get("month")}`;
}

/** "יום שישי" for the chat home's eyebrow (prototype line 1256), in the tenant's timezone. */
export function weekdayText(now: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("he-IL", { timeZone, weekday: "long" }).format(now);
}
