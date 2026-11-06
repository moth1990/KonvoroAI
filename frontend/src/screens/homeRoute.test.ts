import { describe, expect, it } from "vitest";

import type { QuoteListItem } from "../api/client";
import { arrival, choiceArrival, homeSuggestions, missingIn, spokenName } from "./homeRoute";

const recent: QuoteListItem = {
  id: "quo_1",
  name: "NURSERY-1_merged.pdf",
  missing_prices: 0,
  updated_at: "2026-11-06T08:00:00Z",
  version: 1,
  version_status: "draft",
};

describe("arrival", () => {
  it("the builder gets the text as its first message", () => {
    expect(arrival({ to: "/build", text: '12 מא"ז 1X16', chat: false })).toEqual({
      to: "/build",
      state: { text: '12 מא"ז 1X16' },
    });
  });

  it("a quote opens with its chat and the question", () => {
    expect(arrival({ to: "/review/quo_1", text: "מה חסר?", chat: true })).toEqual({
      to: "/review/quo_1",
      state: { chat: true, ask: "מה חסר?", token: expect.stringContaining("מה חסר?") as unknown },
    });
    expect(arrival({ to: "/review/quo_1", text: null, chat: false })).toEqual({ to: "/review/quo_1" });
  });

  it("nowhere to go is null; a choice always goes", () => {
    expect(arrival({ to: null, text: null, chat: false })).toBeNull();
    expect(choiceArrival({ label: "הצעה משרטוט", to: "/new", text: null, chat: false, note: null })).toEqual({
      to: "/new",
    });
  });
});

describe("homeSuggestions", () => {
  it("the build suggestion appears only with the builder, the quote question only with the chat", () => {
    expect(homeSuggestions({ chat_quote_builder: true, chat_layer: true }, recent)).toEqual([
      'בנה הצעה ללוח 3 פאזות 63A עם 12 מא"ז 1X16',
      "מה חסר בהצעה של NURSERY-1?",
      "בדוק הצעה קיימת מול השרטוט",
      "אילו מחירים חסרים במחירון?",
    ]);
    expect(homeSuggestions({}, recent)).toEqual(["בדוק הצעה קיימת מול השרטוט", "אילו מחירים חסרים במחירון?"]);
    expect(homeSuggestions({ chat_layer: true }, null)).toHaveLength(2);
  });

  it("a question about a quote whose name says it is one", () => {
    expect(missingIn("הצעה בצ'אט 06.11 09:37")).toBe("מה חסר בהצעה בצ'אט 06.11 09:37?");
    expect(missingIn("NURSERY-1_merged.pdf")).toBe("מה חסר בהצעה של NURSERY-1?");
  });

  it("a quote's name as said", () => {
    expect(spokenName("לוח-בית-כנסת.pdf")).toBe("לוח-בית-כנסת");
    expect(spokenName("הצעה בצ'אט 06.11")).toBe("הצעה בצ'אט 06.11");
  });
});
