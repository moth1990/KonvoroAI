import { describe, expect, it } from "vitest";

import { examplePrice, markupRate, ratePercentText } from "./model";

describe("the markup question (10 §5.1)", () => {
  it("turns a percent into the rate the API takes, as a string", () => {
    expect(markupRate("25")).toBe("0.25");
    expect(markupRate(" 12.5 ")).toBe("0.125");
    expect(markupRate("0")).toBe("0");
    expect(markupRate("100")).toBe("1");
    expect(markupRate("500")).toBe("5");
    expect(markupRate("7.05")).toBe("0.0705");
  });

  it("refuses what is not a percent up to 500", () => {
    for (const bad of ["", "abc", "-5", "500.01", "1000", "12.345", "25%", "1,5"]) expect(markupRate(bad)).toBeNull();
  });

  it("shows the example the way the question writes it", () => {
    expect(examplePrice("25")).toBe("₪125");
    expect(examplePrice("12.5")).toBe("₪112.50");
    expect(examplePrice("0")).toBe("₪100");
    expect(examplePrice("x")).toBeNull();
  });

  it("shows a stored rate as the percent", () => {
    expect(ratePercentText("0.2500")).toBe("25");
    expect(ratePercentText("0.125")).toBe("12.5");
    expect(ratePercentText("1.0000")).toBe("100");
    expect(ratePercentText("0")).toBe("0");
  });
});
