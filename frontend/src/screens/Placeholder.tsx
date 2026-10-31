import { useMe } from "../api/QueryProvider";
import { quotaView } from "../shell/quota";
import { Shell, useSignOut } from "../shell/Shell";

/** Screens later sessions build (see docs/roadmap.md). Titles are the prototype's `shell(..., {title})` values. */
export const PLACEHOLDERS = {
  new: "הצעה חדשה",
  review: "בדיקת ההצעה",
  audit: "בדיקת הצעה קיימת",
  prices: "מחירון",
  queue: "תור אישור",
  prefs: "הגדרות",
  build: "הצעה בצ'אט",
} as const;

export function Placeholder({ screen }: { screen: keyof typeof PLACEHOLDERS }) {
  const title = PLACEHOLDERS[screen];
  const me = useMe();
  const signOut = useSignOut();
  const blocked = screen === "new" && me.data ? quotaView(me.data.quota).blocked : false;
  return (
    <Shell title={title}>
      <section className="card" style={{ padding: 16, display: "grid", gap: 12, justifyItems: "start" }}>
        {blocked ? (
          <p style={{ margin: 0 }}>אי אפשר להתחיל הצעה חדשה החודש. ההצעות הקיימות זמינות כרגיל.</p>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            המסך הזה עוד בבנייה.
          </p>
        )}
        {screen === "prefs" && (
          <button type="button" className="btn sm" data-testid="logout-prefs" onClick={signOut}>
            יציאה
          </button>
        )}
      </section>
    </Shell>
  );
}
