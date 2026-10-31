import { describe, expect, it } from "vitest";

import { buildTheme } from "./theme";
import { resolveColorMode } from "./ThemeRoot";
import { tokens } from "./tokens";

describe("buildTheme", () => {
  it.each(["light", "dark"] as const)("%s theme is RTL and uses the prototype accent", (mode) => {
    const theme = buildTheme(mode);
    expect(theme.direction).toBe("rtl");
    expect(theme.palette.mode).toBe(mode);
    expect(theme.palette.primary.main).toBe(tokens[mode].colors.accent);
    expect(theme.palette.background.default).toBe(tokens[mode].colors.bg);
    expect(theme.palette.error.main).toBe(tokens[mode].colors.bad);
  });
});

describe("resolveColorMode", () => {
  it("data-theme wins over the OS setting", () => {
    expect(resolveColorMode("light", true)).toBe("light");
    expect(resolveColorMode("dark", false)).toBe("dark");
  });

  it("follows the OS without data-theme", () => {
    expect(resolveColorMode(null, true)).toBe("dark");
    expect(resolveColorMode(null, false)).toBe("light");
    expect(resolveColorMode("unknown", true)).toBe("dark");
  });
});
