// Zu einem Befund springen: Ansicht ausrichten, Wiedergabe mit Vorlauf starten, Eintrag markieren.

import { qs } from "../../core/dom.js";

/** Startzeit der Wiedergabe vor einem Befund (Sekunden oder ganze Takte Vorlauf). */
export function prerollStart(view, time) {
  const { preroll } = view.state;
  const bars = view.result.bars;
  if (!preroll.startsWith("bar")) return Math.max(time - Number(preroll), 0);
  const k = bars.findIndex((b) => b.start <= time + 1e-6 && time < b.end);
  const back = Number(preroll.slice(3));
  if (k < 0) return Math.max(time - 2 * back, 0);
  // Taktanfang des Befund-Takts minus (Vorlauf − 1) weitere Takte; liegt der Befund am Taktanfang, einen Takt mehr
  const idx = Math.max(k - back + (time - bars[k].start > 0.05 ? 1 : 0), 0);
  return bars[idx].start;
}

export function selectIssue(view, issueId, play) {
  const issue = view.issues.find((x) => String(x.id) === String(issueId));
  if (!issue) return;
  const { state, el } = view;
  state.selected = issue.id;
  const from = prerollStart(view, issue.time);
  const width = el.roll.clientWidth;
  // Befund bei ~40 % der Breite; wenn möglich auch den Startpunkt der Wiedergabe sichtbar halten
  let left = issue.time * state.pps - width * 0.4;
  if (from * state.pps < left + width * 0.03 && issue.time * state.pps - from * state.pps < width * 0.8) left = from * state.pps - width * 0.05;
  el.scroll.scrollLeft = Math.max(left, 0);
  el.audio.currentTime = from;
  if (play) el.audio.play();
  view.renderIssues();
  qs(`.issue[data-id="${CSS.escape(String(issue.id))}"]`)?.scrollIntoView({ block: "nearest" });
  view.draw();
}

/** Befund aus Serverdaten anspringen: Timing-Befunde rechnet die Oberfläche selbst neu (eigene IDs) – dann über die Note. */
export function jumpToServerIssue(view, issueId) {
  if (view.issues.some((i) => String(i.id) === String(issueId))) return selectIssue(view, issueId, true);
  const srv = view.result.issues.find((i) => i.id === issueId);
  if (!srv) return;
  const local = srv.note_id != null && view.issues.find((i) => i.note_id === srv.note_id);
  if (local) return selectIssue(view, local.id, true);
  const { el, state } = view;
  el.audio.currentTime = prerollStart(view, srv.time);
  el.scroll.scrollLeft = Math.max(srv.time * state.pps - el.roll.clientWidth * 0.4, 0);
  el.audio.play();
  view.draw();
}
