// Ersatzdarstellung ohne Notensatz (MIDI-Vorlage oder nicht lesbare Datei): kleiner Pianoroll-Ausschnitt fürs Papier.

import { noteName } from "../../core/format.js";

const HEIGHT = 150;
const SCALE = 2;  // scharf im PDF

/** `window`: {start, end} in Sekunden, `marks`: {note, det, time, pitch, color, label}. */
export function renderRollExcerpt(el, result, window, marks) {
  const width = el.clientWidth || 680;
  const canvas = document.createElement("canvas");
  canvas.width = width * SCALE;
  canvas.height = HEIGHT * SCALE;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${HEIGHT}px`;
  el.replaceChildren(canvas);
  const ctx = canvas.getContext("2d");
  ctx.scale(SCALE, SCALE);

  const inWindow = (onset, dur) => onset + dur >= window.start && onset <= window.end;
  const notes = result.notes.filter((n) => inWindow(n.onset, n.duration));
  const dets = result.detected.filter((d) => inWindow(d.onset, d.duration));
  const pitches = [...notes, ...dets].map((n) => n.pitch).concat(marks.map((m) => m.pitch).filter((p) => p != null));
  const pLo = Math.min(...pitches) - 2;
  const pHi = Math.max(...pitches) + 2;
  const top = 18;
  const left = 34;
  const row = (HEIGHT - top - 4) / (pHi - pLo + 1);
  const X = (t) => left + ((t - window.start) / (window.end - window.start)) * (width - left - 4);
  const Y = (p) => top + (pHi - p) * row;

  ctx.font = "9px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  for (let p = pLo; p <= pHi; p++) {
    if (p % 12 !== 4 && p % 12 !== 9) continue;  // Orientierung an E und A
    ctx.fillStyle = "#e6e9ef";
    ctx.fillRect(left, Y(p), width - left - 4, row);
    ctx.fillStyle = "#666";
    ctx.fillText(noteName(p), 2, Y(p) + row / 2);
  }
  ctx.strokeStyle = "#b8c0cc";
  for (const bar of result.bars.filter((b) => b.start >= window.start - 1e-3 && b.start <= window.end)) {
    ctx.beginPath(); ctx.moveTo(X(bar.start), top - 4); ctx.lineTo(X(bar.start), HEIGHT - 4); ctx.stroke();
    ctx.fillStyle = "#666";
    ctx.fillText(String(bar.number), X(bar.start) + 2, 7);
  }
  ctx.fillStyle = "#9aa6b8";
  for (const d of dets) ctx.fillRect(X(d.onset), Y(d.pitch) + row * 0.3, Math.max(X(d.onset + d.duration) - X(d.onset), 2), row * 0.4);
  const marked = new Map(marks.filter((m) => m.note).map((m) => [m.note.id, m.color]));
  for (const n of notes) {
    ctx.strokeStyle = marked.get(n.id) || "#6b7f9e";
    ctx.lineWidth = marked.has(n.id) ? 2 : 1;
    ctx.strokeRect(X(n.onset), Y(n.pitch) + 0.5, Math.max(X(n.onset + n.duration) - X(n.onset), 3), Math.max(row - 1, 2));
  }
  ctx.font = "bold 11px system-ui, sans-serif";
  ctx.textAlign = "center";
  for (const m of marks) {
    const pitch = m.pitch ?? m.note?.pitch;
    ctx.fillStyle = m.color;
    ctx.fillText(m.label, X(m.time), pitch != null ? Math.max(Y(pitch) - 6, 8) : 8);
  }
}
