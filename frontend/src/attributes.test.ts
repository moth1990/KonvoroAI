// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { ATTRIBUTES, attributeFieldLabel, attributeLabel, attributeUnit } from "./attributes";

// 05 §4.4's schemas are data in the backend: every attribute there is made with `_a("name", …)`
const schemas = readFileSync(
  fileURLToPath(new URL("../../backend/konboro/pipeline/association/schemas.py", import.meta.url)),
  "utf8",
);
const schemaAttributes = [...new Set([...schemas.matchAll(/_a\("([a-z0-9_]+)"/g)].map((m) => m[1] ?? ""))];

describe("attribute names (BUG-101)", () => {
  it("reads the schema's attributes", () => {
    expect(schemaAttributes).toEqual(expect.arrayContaining(["current_a", "poles", "neutral", "range_min_a"]));
    expect(schemaAttributes.length).toBeGreaterThan(25);
  });

  it.each(schemaAttributes)("names the schema attribute %s in Hebrew", (key) => {
    const label = attributeLabel(key);
    expect(label).not.toBe(key);
    expect(label === "IP" || /[֐-׿]/.test(label)).toBe(true);
  });

  it("names a BOM breaker's attributes, not by their keys", () => {
    expect(["neutral", "setting_a", "trip_unit", "range_min_a", "range_max_a"].map(attributeLabel)).toEqual([
      "אפס (N)",
      "כיול",
      "יחידת הגנה",
      "טווח מ-",
      "טווח עד",
    ]);
  });

  it("tells apart two attributes the line's wording names alike", () => {
    const labels = Object.values(ATTRIBUTES).map((a) => a.label);
    expect(attributeLabel("range_min_a")).not.toBe(attributeLabel("range_max_a"));
    expect(attributeLabel("ratio_primary_a")).not.toBe(attributeLabel("ratio_secondary_a"));
    expect(labels.every((l) => l.trim() === l && l !== "")).toBe(true);
  });

  it("puts the unit over a field and keeps it out of the name", () => {
    expect(attributeFieldLabel("setting_a")).toBe("כיול (A)");
    expect(attributeFieldLabel("coil_voltage_v")).toBe("מתח סליל (V)");
    expect(attributeFieldLabel("poles")).toBe("קטבים");
    expect(attributeLabel("breaking_capacity_ka")).toBe("כושר ניתוק");
    expect(attributeUnit("residual_ma")).toBe("mA");
  });

  it("shows an unknown key as itself", () => {
    expect(attributeLabel("not_an_attribute")).toBe("not_an_attribute");
    expect(attributeFieldLabel("not_an_attribute")).toBe("not_an_attribute");
  });
});
