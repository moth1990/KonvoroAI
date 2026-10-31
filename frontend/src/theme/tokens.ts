/**
 * Design tokens, ported verbatim from the prototype (prototype/konboro-app.html, :root at lines 9–32).
 * The prototype is the visual reference (CLAUDE.md), so values here change only when the prototype does.
 * tokens.test.ts parses the prototype and fails if the two drift apart.
 */

export const colorKeys = [
  "bg",
  "surface",
  "surface-2",
  "line",
  "line-strong",
  "fg",
  "muted",
  "faint",
  "accent",
  "accent-ink",
  "accent-soft",
  "copper",
  "ok",
  "ok-soft",
  "warn",
  "warn-soft",
  "bad",
  "bad-soft",
] as const;

export type ColorKey = (typeof colorKeys)[number];
export type ColorMode = "light" | "dark";

export interface ModeTokens {
  colors: Record<ColorKey, string>;
  shadow: string;
}

export const tokens: Record<ColorMode, ModeTokens> = {
  light: {
    colors: {
      bg: "#F2F4F7",
      surface: "#FFFFFF",
      "surface-2": "#EBEEF3",
      line: "#D9DEE6",
      "line-strong": "#C3CAD5",
      fg: "#17202B",
      muted: "#5A6576",
      faint: "#8A94A3",
      accent: "#2747C6",
      "accent-ink": "#FFFFFF",
      "accent-soft": "#E7ECFB",
      copper: "#B5693A",
      ok: "#1D8456",
      "ok-soft": "#E1F3EA",
      warn: "#A86F12",
      "warn-soft": "#FBF0D9",
      bad: "#C2372C",
      "bad-soft": "#FBE5E2",
    },
    shadow: "0 1px 2px rgba(20,30,50,.06),0 8px 24px rgba(20,30,50,.06)",
  },
  dark: {
    colors: {
      bg: "#0E131A",
      surface: "#151C26",
      "surface-2": "#1B2430",
      line: "#28323F",
      "line-strong": "#364253",
      fg: "#E6EBF2",
      muted: "#9BA6B5",
      faint: "#6F7A8A",
      accent: "#8199FF",
      "accent-ink": "#0B1020",
      "accent-soft": "#1D294D",
      copper: "#D38C5B",
      ok: "#4DC48C",
      "ok-soft": "#11301F",
      warn: "#E3AB4B",
      "warn-soft": "#33270E",
      bad: "#F27A6E",
      "bad-soft": "#3A1916",
    },
    shadow: "0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25)",
  },
};

export const fonts = {
  display: '"Rubik","IBM Plex Sans Hebrew",system-ui,sans-serif',
  body: '"IBM Plex Sans Hebrew","Rubik",system-ui,sans-serif',
  mono: '"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,monospace',
} as const;

/** Radii in px: --r-sm, --r, --r-lg. */
export const radii = { sm: 6, md: 10, lg: 14 } as const;

/**
 * Phone layout at this width and below: 09 §5.2's 860px, not the prototype's 820px (S04 decision).
 * CSS media queries can't read variables, so app.css repeats the number; tokens.test.ts keeps them equal.
 */
export const MOBILE_MAX_PX = 860;

/** Base type from the prototype body rule: 14px / 1.5. Headings h1 22, h2 17, h3 14, all 600. */
export const type = { base: 14, lineHeight: 1.5, h1: 22, h2: 17, h3: 14 } as const;

/** Declarations for one mode, e.g. "--bg:#F2F4F7;--surface:#FFFFFF;…". */
export function modeVars(mode: ColorMode): string {
  const t = tokens[mode];
  const colors = colorKeys.map((k) => `--${k}:${t.colors[k]}`).join(";");
  return `${colors};--shadow:${t.shadow}${mode === "dark" ? ";color-scheme:dark" : ""}`;
}

/**
 * The prototype's :root rules, as CSS. Dark follows the OS unless data-theme="light" is set;
 * data-theme="dark" forces dark. Same selectors as the prototype, so its CSS ports unchanged.
 */
export function rootCss(): string {
  const shared =
    `--font-display:${fonts.display};--font-body:${fonts.body};--font-mono:${fonts.mono};` +
    `--r-sm:${radii.sm}px;--r:${radii.md}px;--r-lg:${radii.lg}px`;
  return [
    `:root{${modeVars("light")};${shared}}`,
    `@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){${modeVars("dark")}}}`,
    `:root[data-theme="dark"]{${modeVars("dark")}}`,
  ].join("\n");
}
