/**
 * The Hebrew name and unit of every product attribute, the one table the screens name attributes by (BUG-101):
 * the line detail's "מאיפה כל ערך" (09 §6.4), the "מוצר חדש" form (09 §7.16) and its "חסר:" list.
 *
 * The keys are 05 §4.4's schema attributes (`backend/konboro/pipeline/association/schemas.py`; `attributes.test.ts`
 * fails for a schema attribute missing here), then the keys the S09 review fixture still carries. The names follow
 * the line's own wording (`matching/text.py` `NAMES`, 05 §8), told apart where one name there covers two attributes.
 */
export type AttributeName = { label: string; unit?: string };

export const ATTRIBUTES: Record<string, AttributeName> = {
  // 05 §4.4, by family
  current_a: { label: "זרם", unit: "A" },
  poles: { label: "קטבים" },
  curve: { label: "עקומה" },
  breaking_capacity_ka: { label: "כושר ניתוק", unit: "kA" },
  neutral: { label: "אפס (N)" },
  setting_a: { label: "כיול", unit: "A" },
  trip_unit: { label: "יחידת הגנה" },
  range_min_a: { label: "טווח מ-", unit: "A" },
  range_max_a: { label: "טווח עד", unit: "A" },
  residual_ma: { label: "זרם פחת", unit: "mA" },
  rcd_type: { label: "סוג פחת" },
  coil_voltage_v: { label: "מתח סליל", unit: "V" },
  utilization: { label: "קטגוריית עבודה" },
  astronomical: { label: "שעון אסטרונומי" },
  imax_ka: { label: "זרם פריקה", unit: "kA" },
  spd_class: { label: "דרגה" },
  ratio_primary_a: { label: "יחס השנאה, ראשוני", unit: "A" },
  ratio_secondary_a: { label: "יחס השנאה, משני", unit: "A" },
  color: { label: "צבע" },
  positions: { label: "מצבים" },
  cross_section_mm2: { label: "חתך", unit: "mm²" },
  contacts: { label: "מגעים" },
  socket_standard: { label: "תקן" },
  modules: { label: "מודולים" },
  height_mm: { label: "גובה", unit: "mm" },
  width_mm: { label: "רוחב", unit: "mm" },
  depth_mm: { label: "עומק", unit: "mm" },
  ip: { label: "IP" },
  length_mm: { label: "אורך", unit: "mm" },
  // the circuit's load current (04 §5.1 INC=), beside a device's own values
  load_current_a: { label: "זרם עומס (INC)", unit: "A" },
  // the S09 fixture's keys (devtools/fixtures/nursery.py)
  current: { label: "זרם" },
  series: { label: "דגם" },
  load_current: { label: "זרם עומס (INC)" },
  type: { label: "סוג" },
  colors: { label: "צבע" },
  ac3_current: { label: "זרם AC-3" },
  coil_voltage: { label: "מתח סליל" },
  dimensions: { label: "מידות" },
  ik: { label: "IK" },
};

/** The attribute's name, as the line detail and "חסר:" show it; an unknown key as itself. */
export function attributeLabel(key: string): string {
  return ATTRIBUTES[key]?.label ?? key;
}

/** The attribute's name over a field the user types into: with its unit, so a bare number is enough ("כיול (A)"). */
export function attributeFieldLabel(key: string): string {
  const unit = ATTRIBUTES[key]?.unit;
  return unit ? `${attributeLabel(key)} (${unit})` : attributeLabel(key);
}

export function attributeUnit(key: string): string | undefined {
  return ATTRIBUTES[key]?.unit;
}
