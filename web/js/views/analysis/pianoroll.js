// Pianoroll (Vorlage, erkannte Töne, Befunde) und Wellenform auf zwei Canvas-Flächen.

import { cssVar } from "../../core/dom.js";
import { noteName } from "../../core/format.js";
import { CATEGORY_COLORS, catOf } from "./categories.js";

export const ROLL_H = 440;
export const WAVE_H = 80;
export const RULER = 30;

export function createPianoroll(view) {
  const { el, state, model, result, peaks } = view;
  const { pMin, pMax } = model;
  const rowHeight = () => (ROLL_H - RULER) / (pMax - pMin + 1);

  function size() {
    const width = el.scroll.clientWidth;
    const dpr = window.devicePixelRatio || 1;
    el.spacer.style.width = `${Math.ceil(model.duration * state.pps)}px`;
    for (const [canvas, height] of [[el.roll, ROLL_H], [el.wave, WAVE_H]]) {
      canvas.width = Math.floor(width * dpr); canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
      canvas.style.marginTop = canvas === el.roll ? "-1px" : "0";
    }
  }

  let frame = 0;
  function draw() {
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; drawRoll(); drawWave(); });
  }

  function drawRoll() {
    const ctx = el.roll.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const W = el.roll.width / dpr, H = ROLL_H;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const t0 = el.scroll.scrollLeft / state.pps, t1 = t0 + W / state.pps;
    const row = rowHeight();
    const X = (t) => (t - t0) * state.pps;
    const Y = (p) => RULER + (pMax - p) * row;
    const colors = Object.fromEntries(Object.entries(CATEGORY_COLORS).map(([k, c]) => [k, cssVar(c)]));
    const visible = view.visibleIssues();

    // Zeilen und Oktaven
    for (let p = pMin; p <= pMax; p++) {
      if ([1, 3, 6, 8, 10].includes(p % 12)) { ctx.fillStyle = cssVar("--row-alt"); ctx.fillRect(0, Y(p), W, row); }
      if (p % 12 === 0) {
        ctx.fillStyle = cssVar("--grid"); ctx.fillRect(0, Y(p) + row - 0.5, W, 1);
        ctx.fillStyle = cssVar("--muted"); ctx.font = "10px system-ui"; ctx.fillText(noteName(p), 4, Y(p) + row - 2);
      }
    }
    // Takte mit Fehlerdichte
    ctx.font = "11px system-ui";
    for (const b of result.bars) {
      if (b.end < t0 || b.start > t1) continue;
      const weight = visible.filter((i) => i.time >= b.start && i.time < b.end).reduce((s, i) => s + i.confidence, 0);
      ctx.fillStyle = `rgba(${cssVar("--heat")}, ${Math.min(weight / 3, 1) * 0.55})`;
      ctx.fillRect(X(b.start), 0, X(b.end) - X(b.start), RULER - 12);
      ctx.fillStyle = cssVar("--grid-strong"); ctx.fillRect(Math.round(X(b.start)), 0, 1, H);
      ctx.fillStyle = cssVar("--text");
      ctx.fillText(`${b.number}${b.occurrence > 1 ? ` (${b.occurrence}.)` : ""}`, X(b.start) + 4, 12);
      const beat = (b.end - b.start) / b.beats;
      ctx.fillStyle = cssVar("--grid");
      for (let k = 1; k < b.beats; k++) ctx.fillRect(Math.round(X(b.start + k * beat)), RULER - 12, 1, H);
    }
    ctx.fillStyle = cssVar("--grid-strong"); ctx.fillRect(0, RULER - 12, W, 1);

    // nachklingende Pausen: Bereich hinterlegen
    for (const i of visible) {
      if (i.type !== "rest_ringing" || i.rest_end == null || i.rest_end < t0 || i.time > t1) continue;
      const x0 = X(i.time), x1 = X(i.rest_end);
      ctx.fillStyle = colors.stops; ctx.globalAlpha = 0.14; ctx.fillRect(x0, RULER - 12, x1 - x0, H); ctx.globalAlpha = 1;
      ctx.strokeStyle = colors.stops; ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
      ctx.strokeRect(x0 + 0.5, RULER - 11.5, x1 - x0 - 1, H - RULER + 11); ctx.setLineDash([]);
      if (i.played_pitch != null && i.played_pitch >= pMin && i.played_pitch <= pMax) {
        ctx.fillStyle = colors.stops; ctx.globalAlpha = 0.5;
        ctx.fillRect(x0, Y(i.played_pitch) + row * 0.3, x1 - x0, Math.max(row * 0.4, 2)); ctx.globalAlpha = 1;
      }
    }

    const issueColorByNote = new Map();
    for (const i of visible) if (i.note_id != null && !issueColorByNote.has(i.note_id)) issueColorByNote.set(i.note_id, colors[catOf(i.type)]);

    // erkannte Noten
    for (const d of result.detected) {
      if (d.onset + d.duration < t0 || d.onset > t1) continue;
      const extra = visible.find((i) => i.type === "extra" && i.det_id === d.id);
      if (!d.matched && !extra) continue;
      if (d.pitch < pMin || d.pitch > pMax) {
        if (extra) {  // außerhalb des Bereichs: Pfeil am Rand mit Notenname
          const above = d.pitch > pMax, y = above ? RULER + 1 : H - 1;
          ctx.fillStyle = colors.notes; ctx.font = "bold 10px system-ui";
          ctx.fillText(`${above ? "▲" : "▼"} ${noteName(d.pitch)}`, X(d.onset), above ? y + 10 : y - 2);
        }
        continue;
      }
      ctx.fillStyle = extra ? colors.notes : cssVar("--det");
      ctx.globalAlpha = extra ? 0.9 : 0.7;
      ctx.fillRect(X(d.onset), Y(d.pitch) + row * 0.32, Math.max(d.duration * state.pps, 2), Math.max(row * 0.36, 2));
      ctx.globalAlpha = 1;
    }
    // Vorlagennoten
    const okColor = cssVar("--note-ok");
    const selectedNote = state.selected != null ? view.issues.find((i) => i.id === state.selected)?.note_id : null;
    for (const n of result.notes) {
      if (n.onset + n.duration < t0 || n.onset > t1) continue;
      const x = X(n.onset), y = Y(n.pitch), w = Math.max(n.duration * state.pps, 3), h = Math.max(row - 1, 2);
      const color = issueColorByNote.get(n.id) || okColor;
      ctx.strokeStyle = color; ctx.lineWidth = selectedNote === n.id ? 2.5 : 1.3;
      const absent = n.status === "missing" || n.status === "omitted";
      if (n.status === "omitted" && !issueColorByNote.has(n.id)) ctx.strokeStyle = cssVar("--muted");
      ctx.setLineDash(absent ? [4, 3] : n.weak || n.status === "unchecked" ? [1.5, 2] : []);
      ctx.fillStyle = color; ctx.globalAlpha = absent ? 0.05 : 0.16;
      ctx.fillRect(x, y, w, h); ctx.globalAlpha = 1;
      ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
      ctx.setLineDash([]);
      if (n.palm_mute) { ctx.fillStyle = colors.pm; ctx.fillRect(x, y + h - 2.5, w, 2.5); }
      ctx.fillStyle = color; ctx.font = `${Math.min(Math.max(row, 9), 13)}px system-ui`;
      if (n.harmonic) ctx.fillText("◇", x - 9, y + h - 1);
      if (n.dead) ctx.fillText("×", x + 2, y + h - 1);
      if (n.legato) { ctx.beginPath(); ctx.strokeStyle = color; ctx.lineWidth = 1.2; ctx.arc(x, y - 1, 6, Math.PI * 1.1, Math.PI * 1.9); ctx.stroke(); }
      if (n.played_pitch != null && n.played_pitch !== n.pitch && n.played_pitch >= pMin && n.played_pitch <= pMax) {
        ctx.strokeStyle = colors.notes; ctx.setLineDash([2, 2]); ctx.beginPath();
        ctx.moveTo(x + 2, y + h / 2); ctx.lineTo(x + 2, Y(n.played_pitch) + row / 2); ctx.stroke(); ctx.setLineDash([]);
      }
      if (n.bend) {
        ctx.strokeStyle = colors.bend; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]); ctx.beginPath();
        n.bend.forEach(([bt, s], k) => { const px = X(n.onset + bt), py = Y(n.pitch + s) + row / 2; if (k) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
        ctx.stroke(); ctx.setLineDash([]);
        if (n.contour) {
          ctx.lineWidth = 2; ctx.beginPath();
          n.contour.forEach(([ct, s], k) => { const px = X(ct), py = Y(n.pitch + s) + row / 2; if (k) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
          ctx.stroke();
        }
      }
    }
    if (state.strumEnabled && state.showStrum) drawStrums(ctx, t0, t1, X, Y, row);

    // Befund-Markierungen über den Takten
    for (const i of visible) {
      if (i.time < t0 - 1 || i.time > t1 + 1) continue;
      const x = X(i.time);
      ctx.fillStyle = colors[catOf(i.type)];
      ctx.beginPath(); ctx.moveTo(x - 5, RULER - 11); ctx.lineTo(x + 5, RULER - 11); ctx.lineTo(x, RULER - 3); ctx.fill();
      if (i.id === state.selected) { ctx.globalAlpha = 0.35; ctx.fillRect(x - 1, RULER - 12, 2, H); ctx.globalAlpha = 1; }
    }
    drawSelection(ctx, X, Y, row, H);
    // Abspielposition
    const cx = X(el.audio.currentTime);
    if (cx >= 0 && cx <= W) { ctx.fillStyle = cssVar("--cursor"); ctx.fillRect(Math.round(cx), 0, 1.5, H); }
  }

  // Anschlagrichtung: Pfeil über dem Akkord (wie in Akkordschreibweisen: ↓ = Downstroke); unklar = kleiner Punkt
  function drawStrums(ctx, t0, t1, X, Y, row) {
    const down = cssVar("--strum-down"), up = cssVar("--strum-up");
    let lastX = -1e9;
    for (const n of result.notes) {
      if (!n.chord_lead || !n.strum || n.onset < t0 - 0.2 || n.onset > t1 + 0.2) continue;
      const group = model.chordOf.get(n.id) || [n];
      const top = Y(group[group.length - 1].pitch), bottom = Y(group[0].pitch) + row;
      const x = X(n.strum.attack ?? n.onset);
      if (x - lastX < 9) continue;  // zu dicht: Pfeile würden sich überlagern
      lastX = x;
      const dir = n.strum.dir;
      if (!dir) { ctx.fillStyle = cssVar("--muted"); ctx.globalAlpha = 0.5; ctx.fillRect(x - 1.5, top - 9, 3, 3); ctx.globalAlpha = 1; continue; }
      const len = Math.min(Math.max(bottom - top, 14), 60);
      const y0 = top - 6 - len, y1 = top - 6;
      ctx.strokeStyle = dir === "down" ? down : up; ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, dir === "down" ? y0 : y1); ctx.lineTo(x, dir === "down" ? y1 - 4 : y0 + 4); ctx.stroke();
      const tip = dir === "down" ? y1 : y0, back = dir === "down" ? -6 : 6;
      ctx.beginPath(); ctx.moveTo(x, tip); ctx.lineTo(x - 4, tip + back); ctx.lineTo(x + 4, tip + back); ctx.fill();
    }
  }

  // gewählter Befund: Spalte über die ganze Höhe + kräftiger Rahmen um die betroffene Note
  function drawSelection(ctx, X, Y, row, H) {
    const sel = state.selected != null ? view.issues.find((i) => i.id === state.selected) : null;
    if (!sel) return;
    const n = sel.note_id != null ? model.notesById.get(sel.note_id) : null;
    const d = sel.det_id != null ? model.detById.get(sel.det_id) : null;
    const accent = cssVar("--accent");
    const spans = [];
    if (n) spans.push([n.onset, n.duration, n.pitch]);
    if (d && (!n || sel.type !== "missing")) spans.push([d.onset, d.duration, d.pitch]);
    if (!spans.length) spans.push([sel.time, sel.rest_end != null ? sel.rest_end - sel.time : 0.05, sel.played_pitch ?? null]);
    for (const [t, dur, p] of spans) {
      const x = X(t), w = Math.max(dur * state.pps, 6);
      ctx.fillStyle = accent; ctx.globalAlpha = 0.1; ctx.fillRect(x - 3, RULER - 12, w + 6, H); ctx.globalAlpha = 1;
      if (p != null && p >= pMin && p <= pMax) {
        ctx.strokeStyle = accent; ctx.lineWidth = 3; ctx.setLineDash([]);
        ctx.strokeRect(x - 3, Y(p) - 3, w + 6, Math.max(row, 4) + 6);
        ctx.fillStyle = accent; ctx.font = "bold 11px system-ui";
        ctx.fillText(noteName(p), x + w + 6, Y(p) + Math.max(row, 10) - 1);
      }
    }
  }

  function drawWave() {
    const ctx = el.wave.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const W = el.wave.width / dpr, H = WAVE_H;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = cssVar("--grid"); ctx.fillRect(0, 0, W, 1);
    const t0 = el.scroll.scrollLeft / state.pps;
    const per = peaks.per_second, data = peaks.peaks;
    ctx.fillStyle = cssVar("--wave");
    for (let x = 0; x < W; x++) {
      const a = Math.floor((t0 + x / state.pps) * per), b = Math.max(Math.floor((t0 + (x + 1) / state.pps) * per), a + 1);
      let lo = 0, hi = 0;
      for (let k = a; k < b && k < data.length; k++) { if (data[k][0] < lo) lo = data[k][0]; if (data[k][1] > hi) hi = data[k][1]; }
      ctx.fillRect(x, H / 2 - hi * H * 0.48, 1, Math.max((hi - lo) * H * 0.48, 0.5));
    }
    const cx = (el.audio.currentTime - t0) * state.pps;
    if (cx >= 0 && cx <= W) { ctx.fillStyle = cssVar("--cursor"); ctx.fillRect(Math.round(cx), 0, 1.5, H); }
  }

  /** Was liegt unter dem Mauszeiger? Vorlagennote, erkannter Ton, Pause, Befund-Markierung oder Taktkopf. */
  function hitTest(ev) {
    const rect = el.roll.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    const t = el.scroll.scrollLeft / state.pps + mx / state.pps;
    const row = rowHeight();
    const pitch = pMax - Math.floor((my - RULER) / row);
    const pad = 4 / state.pps;
    const note = result.notes.find((n) => n.pitch === pitch && t >= n.onset - 0.02 && t <= n.onset + Math.max(n.duration, pad));
    // erkannte Töne: zusätzliche (rot) haben Vorrang, sonst zugeordnete (grau); dünne Linien bei enger
    // Darstellung auch eine Zeile daneben treffen, wenn dort sonst nichts liegt
    const visible = view.visibleIssues();
    const near = row < 8 ? [pitch, pitch + 1, pitch - 1] : [pitch];
    const detsAt = (p) => result.detected.filter((d) => d.pitch === p && t >= d.onset - pad && t <= d.onset + Math.max(d.duration, pad));
    const dets = note ? detsAt(pitch) : (near.map(detsAt).find((ds) => ds.length) || []);
    const extraIssue = dets.map((d) => visible.find((i) => i.type === "extra" && i.det_id === d.id)).find(Boolean);
    const det = extraIssue ? model.detById.get(extraIssue.det_id) : dets.find((d) => d.matched);
    const rest = visible.find((i) => i.type === "rest_ringing" && i.rest_end != null && t >= i.time && t <= i.rest_end);
    const marker = my < RULER ? visible.find((i) => Math.abs(i.time - t) * state.pps <= 6) : null;
    const bar = my < RULER ? result.bars.find((b) => t >= b.start && t < b.end) : null;
    return { t, inRuler: my < RULER, note, det, extraIssue, rest, marker, bar };
  }

  return { size, draw, hitTest };
}
