import createCache from "@emotion/cache";
import { CacheProvider } from "@emotion/react";
import CssBaseline from "@mui/material/CssBaseline";
import GlobalStyles from "@mui/material/GlobalStyles";
import { ThemeProvider } from "@mui/material/styles";
import { useMemo, useSyncExternalStore, type ReactNode } from "react";
import { prefixer } from "stylis";
import rtlPlugin from "stylis-plugin-rtl";

import { buildTheme } from "./theme";
import { rootCss, type ColorMode } from "./tokens";

// Flips MUI's physical CSS (left/right) for RTL, as MUI's RTL guide prescribes.
const rtlCache = createCache({ key: "muirtl", stylisPlugins: [prefixer, rtlPlugin] });

const darkQuery = "(prefers-color-scheme: dark)";

/** Same rule as the prototype: data-theme on <html> wins, otherwise follow the OS. */
export function resolveColorMode(dataTheme: string | null, osPrefersDark: boolean): ColorMode {
  if (dataTheme === "light" || dataTheme === "dark") return dataTheme;
  return osPrefersDark ? "dark" : "light";
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(darkQuery);
  media.addEventListener("change", onChange);
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => {
    media.removeEventListener("change", onChange);
    observer.disconnect();
  };
}

function currentMode(): ColorMode {
  return resolveColorMode(document.documentElement.getAttribute("data-theme"), window.matchMedia(darkQuery).matches);
}

export function ThemeRoot({ children }: { children: ReactNode }) {
  const mode = useSyncExternalStore(subscribe, currentMode, () => "light" as const);
  const theme = useMemo(() => buildTheme(mode), [mode]);
  return (
    <CacheProvider value={rtlCache}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <GlobalStyles styles={rootCss()} />
        {children}
      </ThemeProvider>
    </CacheProvider>
  );
}
