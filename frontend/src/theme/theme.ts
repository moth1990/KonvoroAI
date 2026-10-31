import { createTheme, type Theme } from "@mui/material/styles";

import { fonts, radii, tokens, type, type ColorMode } from "./tokens";

/**
 * MUI theme for one color mode, built from the prototype tokens. MUI components are restyled
 * to match the prototype, not the other way around (docs/dev-strategy.md §5).
 */
export function buildTheme(mode: ColorMode): Theme {
  const c = tokens[mode].colors;
  return createTheme({
    direction: "rtl",
    palette: {
      mode,
      primary: { main: c.accent, contrastText: c["accent-ink"] },
      secondary: { main: c.copper },
      success: { main: c.ok, light: c["ok-soft"] },
      warning: { main: c.warn, light: c["warn-soft"] },
      error: { main: c.bad, light: c["bad-soft"] },
      background: { default: c.bg, paper: c.surface },
      text: { primary: c.fg, secondary: c.muted, disabled: c.faint },
      divider: c.line,
    },
    shape: { borderRadius: radii.md },
    typography: {
      fontFamily: fonts.body,
      fontSize: type.base,
      // CssBaseline styles <body> with body1; MUI's default (1rem) would override the prototype's 14px / 1.5.
      body1: { fontSize: `${type.base}px`, lineHeight: type.lineHeight },
      h1: { fontFamily: fonts.display, fontSize: type.h1, fontWeight: 600 },
      h2: { fontFamily: fonts.display, fontSize: type.h2, fontWeight: 600 },
      h3: { fontFamily: fonts.display, fontSize: type.h3, fontWeight: 600 },
      button: { textTransform: "none", fontWeight: 500 },
    },
  });
}
