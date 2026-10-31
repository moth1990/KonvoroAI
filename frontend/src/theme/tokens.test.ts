// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { colorKeys, fonts, radii, rootCss, tokens } from "./tokens";

// The prototype is the visual reference. These tests fail if tokens.ts drifts from it.
const prototype = readFileSync(fileURLToPath(new URL("../../../prototype/konboro-app.html", import.meta.url)), "utf8");

/** Parses "--name:value;" declarations from the CSS block that follows `selector`. */
function declarations(selector: string): Map<string, string> {
  const start = prototype.indexOf(selector);
  expect(start, `selector ${selector} not found in the prototype`).toBeGreaterThanOrEqual(0);
  const open = prototype.indexOf("{", start + selector.length - 1);
  const close = prototype.indexOf("}", open);
  const block = prototype.slice(open + 1, close);
  const vars = new Map<string, string>();
  for (const [, name = "", value = ""] of block.matchAll(/--([\w-]+):([^;]+)/g)) vars.set(name, value.trim());
  return vars;
}

const light = declarations(":root{");
const dark = declarations(':root[data-theme="dark"]{');

describe("tokens match the prototype", () => {
  it("light colors", () => {
    for (const key of colorKeys) expect(tokens.light.colors[key], key).toBe(light.get(key));
  });

  it("dark colors", () => {
    for (const key of colorKeys) expect(tokens.dark.colors[key], key).toBe(dark.get(key));
  });

  it("shadows", () => {
    expect(tokens.light.shadow).toBe(light.get("shadow"));
    expect(tokens.dark.shadow).toBe(dark.get("shadow"));
  });

  it("fonts and radii", () => {
    expect(fonts.display).toBe(light.get("font-display"));
    expect(fonts.body).toBe(light.get("font-body"));
    expect(fonts.mono).toBe(light.get("font-mono"));
    expect(`${radii.sm}px`).toBe(light.get("r-sm"));
    expect(`${radii.md}px`).toBe(light.get("r"));
    expect(`${radii.lg}px`).toBe(light.get("r-lg"));
  });

  it("no prototype color is left out", () => {
    const ported = new Set<string>([
      ...colorKeys,
      "shadow",
      "font-display",
      "font-body",
      "font-mono",
      "r-sm",
      "r",
      "r-lg",
    ]);
    expect([...light.keys()].filter((k) => !ported.has(k))).toEqual([]);
  });
});

describe("rootCss", () => {
  it("keeps the prototype's three selectors", () => {
    const css = rootCss();
    expect(css).toContain(":root{--bg:#F2F4F7");
    expect(css).toContain('@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0E131A');
    expect(css).toContain(':root[data-theme="dark"]{--bg:#0E131A');
  });
});
