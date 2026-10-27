// Auswahl der Befunde für den Musiker-Bericht: auf dem Server gespeichert (report.json), solange nichts gespeichert
// ist, vorbelegt aus „Zuerst anhören“ des KI-Checks bzw. mit den sicheren Befunden.

import { api } from "../../core/api.js";
import { getLang } from "../../core/i18n.js";

const TIER_HIGH = 0.7;  // wie analyze.TIER_HIGH

/** Lokaler Befund zu einer Befund-ID des Servers (Timing-Befunde rechnet die Oberfläche selbst neu, eigene IDs). */
export function localIssueFor(view, serverId) {
  const direct = view.issues.find((i) => String(i.id) === String(serverId));
  if (direct) return direct;
  const srv = view.result.issues.find((i) => i.id === serverId);
  return srv?.note_id != null ? view.issues.find((i) => i.note_id === srv.note_id) : undefined;
}

/**
 * Gespeicherten Bericht laden; ohne gespeicherte Auswahl vorbelegen. Vorbelegt wird nur aus `candidates` (in der
 * Analyse: die gerade sichtbaren Befunde), damit im Bericht nichts steht, was die Liste nicht zeigt.
 * Eine automatische Vorbelegung mit den sicheren Befunden wird durch den KI-Check ersetzt, sobald es einen gibt.
 * Ergebnis: { ids: Set<string>, feedback, clef, comments (Befund-ID → Text), source: "user" | "ai" | "confident", auto, timingTolMs }
 */
export async function loadSelection(view, candidates = view.issues) {
  const [saved, ai] = await Promise.all([
    api(`/api/analyses/${view.id}/report`),
    api(`/api/analyses/${view.id}/ai-check?lang=${getLang()}`).catch(() => ({})),
  ]);
  const review = ai.result && !ai.stale ? ai.result.review : null;
  const feedback = saved.feedback ?? review?.musician_feedback ?? "";
  const clef = saved.clef ?? "auto";
  const comments = saved.comments ?? {};
  const keepSaved = saved.issue_ids && !(saved.auto && saved.source === "confident" && review?.listen_first?.length);
  if (keepSaved) {
    return { ids: new Set(saved.issue_ids), feedback, clef, comments, source: saved.source ?? "user", auto: Boolean(saved.auto),
             timingTolMs: saved.timing_tol_ms };
  }
  const allowed = new Set(candidates.map((i) => String(i.id)));
  if (review?.listen_first?.length) {
    const ids = review.listen_first.flatMap((it) => it.issue_ids).map((id) => localIssueFor(view, id))
      .filter(Boolean).map((i) => String(i.id)).filter((id) => allowed.has(id));
    if (ids.length) return { ids: new Set(ids), feedback, clef, comments, source: "ai", auto: true };
  }
  const confident = candidates.filter((i) => i.confidence >= TIER_HIGH).map((i) => String(i.id));
  return { ids: new Set(confident), feedback, clef, comments, source: "confident", auto: true };
}

let pending = null;
let timer;

/** Änderungen gebündelt speichern (Felder, die fehlen, bleiben auf dem Server unverändert). */
export function saveSelection(view, changes) {
  pending = { ...pending, ...changes };
  clearTimeout(timer);
  timer = setTimeout(flushSelection, 400, view.id);
}

export async function flushSelection(id) {
  clearTimeout(timer);
  if (!pending) return;
  const body = pending;
  pending = null;
  await fetch(`/api/analyses/${id}/report`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
}
