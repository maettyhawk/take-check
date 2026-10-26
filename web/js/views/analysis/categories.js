// Befundtypen und ihre Kategorien (Farbe, Filter).

import { t } from "../../core/i18n.js";

export const CATEGORY_COLORS = {
  notes: "--c-notes", timing: "--c-timing", pm: "--c-pm", legato: "--c-legato",
  bend: "--c-bend", harm: "--c-harm", stops: "--c-stops",
};

const TYPE_CATEGORY = {
  missing: "notes", wrong_pitch: "notes", extra: "notes", chord_tone_omitted: "notes",
  early: "timing", late: "timing", short: "timing", slow_strum: "timing",
  pm_missing: "pm", pm_unexpected: "pm", legato_picked: "legato", picked_legato: "legato",
  bend_missing: "bend", bend_pitch: "bend", bend_late: "bend", prebend_missing: "bend", release_missing: "bend",
  unwanted_bend: "bend", vibrato_unexpected: "bend", harmonic_fretted: "harm", harmonic_timbre: "harm",
  rest_ringing: "stops",
};

export const catOf = (type) => TYPE_CATEGORY[type] || "notes";
export const colorOf = (type) => CATEGORY_COLORS[catOf(type)];
export const labelOf = (type) => t(`types.${type}`, {}, type);
