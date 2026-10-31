import { describe, expect, it } from "vitest";

import { homeRoute, homeSuggestions, NO_BUILDER_TOAST } from "./homeRoute";

const on = { chat_quote_builder: true };
const off = { chat_quote_builder: false };

describe("homeRoute", () => {
  it("blank input does nothing", () => {
    expect(homeRoute("   \n", on)).toBeNull();
  });

  it.each(["בדוק את הצעה 10271 מול השרטוט", "בדיקת הצעה של הקבלן", "מה עם 10288?"])("%s -> audit", (text) => {
    expect(homeRoute(text, on)).toEqual({ kind: "go", to: "/audit" });
  });

  it.each(["אילו מחירים חסרים במחירון?", "פתח את המחירון"])("%s -> price list", (text) => {
    expect(homeRoute(text, off)).toEqual({ kind: "go", to: "/prices" });
  });

  it("a panel description goes to the chat builder, carrying the text", () => {
    expect(homeRoute('  לוח 3 פאזות 63A עם 12 מא"ז 1X16 ', on)).toEqual({
      kind: "go",
      to: "/build",
      text: 'לוח 3 פאזות 63A עם 12 מא"ז 1X16',
    });
  });

  it("with the builder off, it points to a drawing and never mentions chat building (13 §3.2)", () => {
    expect(homeRoute("לוח 3 פאזות", off)).toEqual({ kind: "toast", text: NO_BUILDER_TOAST });
    expect(NO_BUILDER_TOAST).not.toContain("צ'אט");
  });
});

describe("homeSuggestions", () => {
  it("the build suggestion appears only with the builder", () => {
    expect(homeSuggestions(on)).toHaveLength(3);
    expect(homeSuggestions(off)).toEqual(["בדוק הצעה קיימת מול השרטוט", "אילו מחירים חסרים במחירון?"]);
  });

  it("every suggestion routes somewhere useful", () => {
    for (const q of homeSuggestions(on)) expect(homeRoute(q, on)?.kind).toBe("go");
    for (const q of homeSuggestions(off)) expect(homeRoute(q, off)?.kind).toBe("go");
  });
});
