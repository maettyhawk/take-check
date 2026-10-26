// Tooltips für alles in der Pianoroll: Vorlagennoten, erkannte Töne, Pausen, Befund-Markierungen, Taktköpfe.

import { esc } from "../../core/dom.js";
import { fmtTime, noteName } from "../../core/format.js";
import { t, tab, where } from "../../core/i18n.js";
import { colorOf, labelOf } from "./categories.js";
import { chordText, msgOf } from "./model.js";

const issueLine = (i) => `<div class="t-issue" style="color:var(${colorOf(i.type)})">● ${esc(msgOf(i))}</div>`;

function barTooltip(view, bar) {
  const n = view.visibleIssues().filter((i) => i.time >= bar.start && i.time < bar.end).length;
  const pass = bar.occurrence > 1 ? t("barPass", { n: bar.occurrence }) : "";
  return `<b>${t("barTitle", { n: bar.number, pass })}</b> · ${bar.beats}/${bar.beat_type} · ${fmtTime(bar.start)}
    <br><span class="muted">${n ? t("barFindings", { n }) : t("barFindingsNone")}</span>`;
}

const markerTooltip = (marker) => `<b>${esc(labelOf(marker.type))}</b> · ${where(marker)}${issueLine(marker)}
  <span class="muted">${t("confShort")} ${marker.confidence.toFixed(2)}</span>`;

const extraTooltip = (det, issue) => `<b>${t("extraTitle")}</b><br><b>${noteName(det.pitch)}</b> · ${where(issue)} · ${fmtTime(det.onset)}
  <br><span class="muted">${t("duration")} ${Math.round(det.duration * 1000)} ms · ${t("confShort")} ${issue.confidence.toFixed(2)}</span>
  ${issueLine(issue)}<div class="muted t-explain">${t("extraExplain")}</div>`;

function detectedTooltip(view, det) {
  const n = view.model.noteOfDet.get(det.id);
  const rel = !n ? ""
    : n.status === "wrong_pitch" ? t("playedInstead", { played: noteName(det.pitch), expected: noteName(n.pitch) })
      : `${t("belongsTo")} ${noteName(n.pitch)} (${where(n)})`;
  return `<b>${t("detTitle")}: ${noteName(det.pitch)}</b> · ${fmtTime(det.onset)}
    <br><span class="muted">${t("duration")} ${Math.round(det.duration * 1000)} ms${rel ? ` · ${rel}` : ""}</span>`;
}

const restTooltip = (rest) => `<b>${t("restTitle")}</b> · ${where(rest)} · ${fmtTime(rest.time)}–${fmtTime(rest.rest_end)}
  ${issueLine(rest)}<div class="muted t-explain">${t("restExplain")}</div>`;

function noteTooltip(view, note) {
  const tech = [note.palm_mute && "Palm Mute", note.legato && "Hammer-on/Pull-off", note.slide && "Slide",
    note.harmonic && `${t("legHarm")} (${note.harmonic}${note.fretted_pitch ? `, ${t("techFretted")} ${noteName(note.fretted_pitch)}` : ""})`,
    note.bend && `Bend +${Math.max(...note.bend.map((b) => b[1]))} ${t("semitones")}`, note.vibrato && "Vibrato",
    note.dead && "Dead Note"].filter(Boolean);
  const status = note.status === "ok" ? t(note.weak ? "st.weak" : "st.ok")
    : note.status === "wrong_pitch" ? `${t("st.wrong_pitch")}: ${noteName(note.played_pitch)}` : t(`st.${note.status}`, {}, note.status);
  const chord = chordText(view, note);
  const fingering = tab(note);
  const delta = note.delta_ms != null ? ` · ${note.delta_ms > 0 ? "+" : ""}${note.delta_ms} ms` : "";
  return `<b>${noteName(note.pitch)}</b> · ${where(note)}${fingering ? ` · ${fingering}` : ""}
    ${tech.length ? `<br>${tech.join(" · ")}` : ""}
    ${chord ? `<br>${chord}` : ""}
    <br><span class="muted">${status}${delta}</span>
    ${view.issues.filter((i) => i.note_id === note.id).map(issueLine).join("")}`;
}

function tooltipHtml(view, hit) {
  if (hit.bar && !hit.marker) return barTooltip(view, hit.bar);
  if (hit.marker) return markerTooltip(hit.marker);
  if (!hit.note && hit.extraIssue && hit.det) return extraTooltip(hit.det, hit.extraIssue);
  if (!hit.note && hit.det) return detectedTooltip(view, hit.det);
  if (!hit.note && hit.rest) return restTooltip(hit.rest);
  if (hit.note && !hit.inRuler) return noteTooltip(view, hit.note);
  return null;
}

export function attachTooltip(view) {
  const { el } = view;
  const place = (ev) => {
    el.tooltip.hidden = false;
    const x = Math.min(ev.clientX + 14, window.innerWidth - el.tooltip.offsetWidth - 8);
    const y = Math.min(ev.clientY + 14, window.innerHeight - el.tooltip.offsetHeight - 8);
    el.tooltip.style.left = `${x}px`; el.tooltip.style.top = `${y}px`;
  };
  el.roll.addEventListener("mousemove", (ev) => {
    const html = tooltipHtml(view, view.pianoroll.hitTest(ev));
    if (!html) { el.tooltip.hidden = true; return; }
    el.tooltip.innerHTML = html;
    place(ev);
  });
  el.roll.addEventListener("mouseleave", () => { el.tooltip.hidden = true; });
}
