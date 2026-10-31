/**
 * Where a request typed on the chat home goes (13 §4.3). For now these are keyword rules, like the prototype's
 * `homeSubmit` (line 1277); real intent comes in S27. The prototype's rule that opens one named demo quote is
 * left out: there is no such quote here.
 */
export type HomeRoute = { kind: "go"; to: string; text?: string } | { kind: "toast"; text: string } | null;

export const NO_BUILDER_TOAST = "כדי ליצור הצעה, צרפו שרטוט או כתב כמויות";

export function homeRoute(text: string, flags: Record<string, boolean>): HomeRoute {
  const t = text.trim();
  if (!t) return null;
  if (/בדוק|בדיקת הצעה|\b\d{4,6}\b/.test(t)) return { kind: "go", to: "/audit" };
  if (/מחירון|מחירים חסרים/.test(t)) return { kind: "go", to: "/prices" };
  // A flag that is off behaves as if the feature does not exist (13 §3.2): no mention of building in chat.
  if (flags.chat_quote_builder) return { kind: "go", to: "/build", text: t };
  return { kind: "toast", text: NO_BUILDER_TOAST };
}

/** Suggestion chips (prototype HOME_SUGG, line 1253), without the one about a named demo quote. */
export function homeSuggestions(flags: Record<string, boolean>): string[] {
  return [
    ...(flags.chat_quote_builder ? ['בנה הצעה ללוח 3 פאזות 63A עם 12 מא"ז 1X16'] : []),
    "בדוק הצעה קיימת מול השרטוט",
    "אילו מחירים חסרים במחירון?",
  ];
}
