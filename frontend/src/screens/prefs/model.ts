/** The settings screen's rows (prototype `vPrefs`, lines 1228–1251), without React. */

import type { DocumentSettings, DocumentSettingsIn, TenantSettings } from "../../api/client";

export type EnclosurePart = keyof TenantSettings["enclosure_includes_default"];
type AttributeDefaults = TenantSettings["attribute_defaults"];

/** S24 decision 2: one select per family, the families onboarding asks about (10 §5.1). */
export const BRAND_ROWS = [
  { family: "circuit_breaker", label: 'מותג מועדף למא"זים' },
  { family: "rcd", label: "מותג מועדף למפסקי פחת" },
] as const;

/** The prototype's options, in its order. */
export const BRANDS = ["ABB", "Schneider", "Hager"] as const;

export const INCLUDES: { part: EnclosurePart; label: string }[] = [
  { part: "busbar", label: "פסי צבירה" },
  { part: "n", label: "פס אפס" },
  { part: "pe", label: "פס הארקה" },
  { part: "panels", label: "פנלים" },
  { part: "doors", label: "דלתות" },
];

/** The prototype's `FLAGS` (line 560), with spec 13's keys (CLAUDE.md: the spec's keys win). */
export const FLAG_ROWS = [
  {
    key: "home_chat",
    name: "מסך בית כשיחה",
    desc: "מסך הבית הוא תיבת שיחה אחת, כמו Claude או Gemini: כותבים, מצרפים קובץ או מדברים",
  },
  {
    key: "chat_quote_builder",
    name: "בניית הצעה בצ'אט",
    desc: "הצעה בלי שרטוט: מתארים את הלוח במילים, והמערכת בונה שורות ומתמחרת מהמחירון",
  },
  {
    key: "voice_input",
    name: "קלט קולי",
    desc: 'הקלטה בעברית, תמלול ונרמול מונחים ("שלוש על שש עשרה" ← 3X16A). דורש את בניית ההצעה בצ\'אט',
  },
  { key: "export_doc", name: "הורדת ההצעה", desc: "PDF ללקוח ו-Excel לעבודה פנימית, מכל גרסה" },
  {
    key: "unresolved_overlay",
    name: "סימון מה לא פוענח",
    desc: "ריבוע אדום על השרטוט סביב כל מה שהמערכת לא זיהתה, או זיהתה רק חלקית",
  },
] as const;

/** The 30 mA toggle is the RCD's `residual_ma` default (05 §4.4: the schema allows one). */
export function rcd30(defaults: AttributeDefaults): boolean {
  return defaults.rcd?.residual_ma === 30;
}

/** On: the RCD gets `residual_ma: 30`; off: it loses it. Every other default is kept. */
export function withRcd30(defaults: AttributeDefaults, on: boolean): AttributeDefaults {
  const rcd = { ...(defaults.rcd ?? {}) };
  if (on) rcd.residual_ma = 30;
  else delete rcd.residual_ma;
  const next: AttributeDefaults = { ...defaults };
  if (Object.keys(rcd).length) next.rcd = rcd;
  else delete next.rcd;
  return next;
}

// --- "המסמך ללקוח" (13 §4.1, §6 item 2; S26 decision 1) ------------------------------------------------------------

export interface DocumentForm {
  name: string;
  company_id: string;
  address: string;
  phone: string;
  terms: string;
  show_sku: boolean;
}

/** The section's fields from the server's template; a detail not set is an empty field. */
export function documentForm(s: DocumentSettings): DocumentForm {
  return {
    name: s.company.name,
    company_id: s.company.company_id ?? "",
    address: s.company.address ?? "",
    phone: s.company.phone ?? "",
    terms: s.terms ?? "",
    show_sku: s.show_sku,
  };
}

export function sameForm(a: DocumentForm, b: DocumentForm): boolean {
  return (Object.keys(a) as (keyof DocumentForm)[]).every((k) => a[k] === b[k]);
}

/** What "שמור" sends: an empty field is not set. */
export function documentBody(f: DocumentForm): DocumentSettingsIn {
  const or = (v: string) => v.trim() || null;
  return {
    company: { name: f.name.trim(), company_id: or(f.company_id), address: or(f.address), phone: or(f.phone) },
    terms: or(f.terms),
    show_sku: f.show_sku,
  };
}
