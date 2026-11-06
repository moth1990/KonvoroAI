/**
 * The chat home (13 §4.3): the server decides where a request goes (`POST /home/route`, S27): code first, a small
 * model for the rest, and a short question with choices when it can't tell. This module turns its answer into a
 * navigation, and keeps the prototype's suggestion chips (`HOME_SUGG`, line 1253).
 */
import type { HomeChoice, HomeRoute, QuoteListItem } from "../api/client";

/** Where to go and what to carry: the build's first message, or the question for the review's chat. */
export function arrival(r: Pick<HomeRoute, "to" | "text" | "chat">): { to: string; state?: object } | null {
  if (!r.to) return null;
  if (r.to.startsWith("/review/"))
    return { to: r.to, state: r.chat ? { chat: true, ask: r.text, token: `${Date.now()}:${r.text}` } : undefined };
  return { to: r.to, state: r.text ? { text: r.text } : undefined };
}

export function choiceArrival(c: HomeChoice): { to: string; state?: object } {
  return arrival(c) ?? { to: c.to };
}

/** A quote's name as the estimator says it: without the file's extension ("NURSERY-1_merged.pdf" → "NURSERY-1"). */
export function spokenName(name: string): string {
  return name
    .replace(/\.(pdf|xlsx?|csv|dwg|png|jpe?g)$/i, "")
    .replace(/[_-]merged$/i, "")
    .trim();
}

/** "מה חסר בהצעה של NURSERY-1?", or for a quote whose name says it is one, "מה חסר בהצעה בצ'אט 06.11 09:37?". */
export function missingIn(name: string): string {
  const said = spokenName(name);
  return said.startsWith("הצעה") ? `מה חסר ב${said}?` : `מה חסר בהצעה של ${said}?`;
}

/**
 * Suggestion chips (prototype HOME_SUGG, line 1253): building in chat (with the builder), a question about the most
 * recent quote (with the chat on the review screen), an audit and the price list.
 */
export function homeSuggestions(flags: Record<string, boolean>, recent?: QuoteListItem | null): string[] {
  return [
    ...(flags.chat_quote_builder ? ['בנה הצעה ללוח 3 פאזות 63A עם 12 מא"ז 1X16'] : []),
    ...(flags.chat_layer && recent ? [missingIn(recent.name)] : []),
    "בדוק הצעה קיימת מול השרטוט",
    "אילו מחירים חסרים במחירון?",
  ];
}
