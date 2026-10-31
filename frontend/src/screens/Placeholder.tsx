import { Shell, useSignOut } from "../shell/Shell";

/** Screens later sessions build (see docs/roadmap.md). Titles are the prototype's `shell(..., {title})` values. */
export const PLACEHOLDERS = {
  review: "בדיקת ההצעה",
  audit: "בדיקת הצעה קיימת",
  prices: "מחירון",
  queue: "תור אישור",
  prefs: "הגדרות",
  build: "הצעה בצ'אט",
} as const;

export function Placeholder({ screen }: { screen: keyof typeof PLACEHOLDERS }) {
  const title = PLACEHOLDERS[screen];
  const signOut = useSignOut();
  return (
    <Shell title={title}>
      <section className="card" style={{ padding: 16, display: "grid", gap: 12, justifyItems: "start" }}>
        <p className="muted" style={{ margin: 0 }}>
          המסך הזה עוד בבנייה.
        </p>
        {screen === "prefs" && (
          <button type="button" className="btn sm" data-testid="logout-prefs" onClick={signOut}>
            יציאה
          </button>
        )}
      </section>
    </Shell>
  );
}
