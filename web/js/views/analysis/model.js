// Aufbereitung des Analyseergebnisses: Nachschlagetabellen, Akkordkontext, Timing gegen den Groove, Befundtexte.

import { fmtTime, noteName } from "../../core/format.js";
import { renderMsg, t, tab } from "../../core/i18n.js";
import { catOf } from "./categories.js";

export function buildModel(result, peaks) {
  const notesById = new Map(result.notes.map((n) => [n.id, n]));
  const detById = new Map(result.detected.map((d) => [d.id, d]));
  const noteOfDet = new Map(result.notes.filter((n) => n.det_id != null).map((n) => [n.det_id, n]));

  // Akkordkontext: alle Vorlagennoten mit demselben Anschlag, tiefste zuerst
  const chordOf = new Map();
  const byOnset = new Map();
  for (const n of result.notes) {
    const k = Math.round(n.onset * 1000);
    if (!byOnset.has(k)) byOnset.set(k, []);
    byOnset.get(k).push(n);
  }
  for (const group of byOnset.values()) {
    group.sort((a, b) => a.pitch - b.pitch);
    for (const n of group) chordOf.set(n.id, group);
  }

  // Tonhöhenbereich nach der Vorlage; gemeldete Töne in der Nähe dazunehmen, weit entfernte Ausreißer
  // werden am Rand angedeutet statt den Bereich aufzublähen
  const scorePitches = result.notes.flatMap((n) => [n.pitch, n.pitch + Math.ceil(Math.max(0, ...(n.bend || [[0, 0]]).map((b) => b[1])))]);
  let pMin = Math.min(...scorePitches) - 3;
  let pMax = Math.max(...scorePitches) + 3;
  for (const p of result.issues.map((i) => i.played_pitch).filter((p) => p != null)) {
    if (p < pMin && p >= pMin - 7) pMin = p - 1;
    if (p > pMax && p <= pMax + 7) pMax = p + 1;
  }
  return { notesById, detById, noteOfDet, chordOf, pMin, pMax, duration: Math.max(result.duration, peaks.duration || 0) };
}

// ---- Befundtexte

const LEGACY_CHORD_SIZE = /\s*\((Akkord mit|chord of) \d+ (Tönen|notes)[^)]*\)/;  // Ergebnisse vor Version 3
const issueText = (i) => i.msg ?? i.messages ?? i.message;

/** Vollständiger Befundtext in der gewählten Sprache. */
export const msgOf = (issue) => renderMsg(issueText(issue));

/** Befundtext ohne vorangestellte Befundart und ohne Akkordgröße (die stehen in der Liste separat). */
export const shortMsg = (issue) => renderMsg(issueText(issue), { skip: ["suffix_chord_size"] })
  .replace(/^[^:]+:\s*/, "").replace(LEGACY_CHORD_SIZE, "");

const CHORD_MARKS = { ok: "✓", missing: "✗", unchecked: "–", dead: "×" };

function strumText(strum) {
  if (!strum) return "";
  const ms = Math.round(strum.spread_ms);
  return strum.dir === "down" ? t("strumDown", { ms }) : strum.dir === "up" ? t("strumUp", { ms }) : t("strumUnclear");
}

/** Akkordkontext einer Note als HTML (die Note selbst fett), leer bei Einzeltönen. */
export function chordText(view, note) {
  const group = view.model.chordOf.get(note.id) || [note];
  if (group.length < 2) return "";
  const strum = view.state.strumEnabled ? strumText(group.find((m) => m.strum)?.strum) : "";
  const marks = group.map((m) => {
    const mark = m.status === "wrong_pitch" ? `→ ${noteName(m.played_pitch)}`
      : m.status === "ok" && m.weak ? "✓?" : m.status === "omitted" ? t("omittedMark") : CHORD_MARKS[m.status] || m.status;
    const label = `${noteName(m.pitch)} ${mark}`;
    return m.id === note.id ? `<b>${label}</b>` : label;
  });
  return `${strum ? strum + " · " : ""}${t("chord")}: ${marks.join(" · ")}`;
}

/** Detailzeile eines Befunds: Saite/Bund und Akkordkontext bzw. Daten des erkannten Tons. */
export function issueDetail(view, issue) {
  const note = issue.note_id != null ? view.model.notesById.get(issue.note_id) : null;
  if (note) return [tab(note), chordText(view, note)].filter(Boolean).join(" · ");
  const det = issue.det_id != null ? view.model.detById.get(issue.det_id) : null;
  return det ? t("detected", { time: fmtTime(det.onset), ms: Math.round(det.duration * 1000) }) : "";
}

// ---- Befunde (Timing clientseitig gegen den Groove neu berechnet, damit der Toleranzregler ohne Neuanalyse wirkt)

export function computeIssues(view) {
  const { result, state, model } = view;
  const tol = state.timingTol / 1000;
  const base = result.issues.filter((i) => i.type !== "early" && i.type !== "late");
  const timing = [];
  for (const n of result.notes) {
    if (n.status !== "ok" || n.weak || n.delta_ms == null) continue;
    const group = model.chordOf.get(n.id) || [n];
    const isChord = group.length > 1;
    // Akkorde: nur der zuerst angeschlagene Ton zählt – die übrigen Saiten folgen je nach Up-/Downstroke
    if (isChord && !n.chord_lead) continue;
    const groove = (n.groove_ms ?? 0) / 1000;
    const dt = (isChord ? n.chord_delta_ms : n.delta_ms) / 1000 - groove;
    const limit = n.legato || n.harmonic ? tol * 1.5 : tol;
    if (Math.abs(dt) <= limit) continue;
    const ms = String(Math.round(Math.abs(dt) * 1000));
    const context = Math.abs(groove) >= 0.008
      ? { k: "groove_context", p: { ms: `${groove > 0 ? "+" : ""}${Math.round(groove * 1000)}` } } : "";
    const arrow = state.strumEnabled && isChord && n.strum?.dir ? (n.strum.dir === "down" ? ", ↓" : ", ↑") : "";
    const msg = isChord
      ? { k: dt > 0 ? "timing_chord_late" : "timing_chord_early", p: { ms, notes: group.map((m) => noteName(m.pitch)).join("·"), arrow, context } }
      : { k: dt > 0 ? "timing_late" : "timing_early", p: { ms, note: noteName(n.pitch), context } };
    timing.push({
      id: `t${n.id}`, type: dt > 0 ? "late" : "early", time: n.onset + dt + groove, bar: n.bar, occurrence: n.occurrence,
      beat: n.beat, note_id: n.id, det_id: n.det_id, confidence: Math.abs(dt) > 2 * limit ? 0.9 : 0.6,
      msg, delta_ms: Math.round(dt * 1000),
    });
  }
  return base.concat(timing).sort((a, b) => a.time - b.time);
}

export const isVisible = (state, issue) => issue.confidence >= state.minConf && state.cats.has(catOf(issue.type));
