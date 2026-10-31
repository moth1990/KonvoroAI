import { colorKeys } from "./theme/tokens";

/** Logo mark from the prototype (konboro-app.html line 378). */
export function Logo() {
  return (
    <span className="logo">
      <span
        aria-hidden="true"
        style={{
          width: 30,
          height: 30,
          borderRadius: 8,
          background: "var(--copper)",
          display: "grid",
          placeItems: "center",
        }}
      >
        <svg
          viewBox="0 0 24 24"
          width="18"
          height="18"
          fill="none"
          stroke="#fff"
          strokeWidth="2.4"
          strokeLinecap="round"
        >
          <path d="M4 7h16M4 12h16M4 17h10" />
        </svg>
      </span>
      קונבורו
    </span>
  );
}

/**
 * Placeholder until the app shell lands in S04: shows the brand and every token,
 * so the theme can be checked by eye in light and dark.
 */
export default function App() {
  return (
    <main style={{ padding: 24, display: "grid", gap: 16, maxWidth: 720 }}>
      <h1 style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Logo />
      </h1>
      <p className="muted">
        שלד הפיתוח. המסכים מגיעים בסשן S04. מק"ט לדוגמה: <span className="des">S203M-C16</span>
      </p>
      <ul
        aria-label="טוקנים"
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "grid",
          gap: 6,
          gridTemplateColumns: "repeat(3, 1fr)",
        }}
      >
        {colorKeys.map((key) => (
          <li key={key} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span
              data-testid={`swatch-${key}`}
              style={{
                width: 22,
                height: 22,
                borderRadius: "var(--r-sm)",
                background: `var(--${key})`,
                border: "1px solid var(--line-strong)",
              }}
            />
            <span className="mono small">--{key}</span>
          </li>
        ))}
      </ul>
    </main>
  );
}
