// Bedienelemente der Analyse: Wiedergabe, Zoom, Toleranz, Vorlauf, Sicherheit, Versatz, Kopieren, Tastatur.

import { postJson } from "../../core/api.js";
import { qs, qsa } from "../../core/dom.js";
import { fmtTime } from "../../core/format.js";
import { renderMsg, t, where } from "../../core/i18n.js";
import { store } from "../../core/store.js";
import { confLabel } from "./issue-list.js";
import { labelOf } from "./categories.js";
import { shortMsg } from "./model.js";

function bindPlayback(view) {
  const { el, state } = view;
  const playBtn = qs("#play");
  playBtn.addEventListener("click", () => (el.audio.paused ? el.audio.play() : el.audio.pause()));
  const tick = () => {
    if (el.audio.paused) return;
    // nur mitscrollen, wenn der Cursor rechts aus dem Bild läuft – sonst bleibt die Ansicht auf dem Befund
    const width = el.roll.clientWidth, x = el.audio.currentTime * state.pps - el.scroll.scrollLeft;
    if (x > width * 0.9) el.scroll.scrollLeft = el.audio.currentTime * state.pps - width * 0.1;
    qs("#clock").textContent = fmtTime(el.audio.currentTime);
    view.draw();
    requestAnimationFrame(tick);
  };
  el.audio.addEventListener("play", () => { playBtn.textContent = "❚❚"; tick(); });
  el.audio.addEventListener("pause", () => { playBtn.textContent = "▶"; view.draw(); });
  el.audio.addEventListener("seeked", () => view.draw());

  const seekClick = (ev) => {
    const hit = view.pianoroll.hitTest(ev);
    const target = hit.note ? view.visibleIssues().find((x) => x.note_id === hit.note.id) : hit.marker || hit.extraIssue || hit.rest;
    if (target) { view.select(target.id, false); return; }
    el.audio.currentTime = Math.max(0, Math.min(hit.t, view.model.duration));
    view.draw();
  };
  el.roll.addEventListener("click", seekClick);
  el.wave.addEventListener("click", seekClick);
  el.scroll.addEventListener("scroll", () => view.draw(), { passive: true });
}

function bindToolbar(view) {
  const { el, state } = view;
  qs("#zoom").addEventListener("input", (ev) => {
    const center = (el.scroll.scrollLeft + el.roll.clientWidth / 2) / state.pps;
    state.pps = +ev.target.value;
    store.set("tc.pps", state.pps);
    view.pianoroll.size();
    el.scroll.scrollLeft = center * state.pps - el.roll.clientWidth / 2;
    view.draw();
  });
  qs("#strum")?.addEventListener("change", (ev) => { state.showStrum = ev.target.checked; store.set("tc.showStrum", state.showStrum); view.draw(); });
  qs("#preroll").value = state.preroll;
  qs("#preroll").addEventListener("change", (ev) => { state.preroll = ev.target.value; store.set("tc.preroll", state.preroll); });
  qs("#tol").addEventListener("input", (ev) => {
    state.timingTol = +ev.target.value;
    qs("#tol-v").textContent = `${state.timingTol} ms`;
    view.refresh();
  });
  qs("#conf-v").textContent = confLabel(state.minConf);
  qs("#conf").addEventListener("input", (ev) => view.setConfidence(+ev.target.value));
}

function bindOffset(view) {
  const { state, result, id } = view;
  qsa("[data-off]").forEach((b) => b.addEventListener("click", () => {
    state.offsetDraft = Math.round((state.offsetDraft + +b.dataset.off) * 1000) / 1000;
    qs("#offset").textContent = `${state.offsetDraft.toFixed(3)} s${state.offsetDraft !== result.offset ? ` (${t("changed")})` : ""}`;
    qs("#apply-offset").disabled = state.offsetDraft === result.offset;
  }));
  const rerun = async (body) => {
    await postJson(`/api/analyses/${id}/rerun`, body);
    view.el.audio.pause();
    view.reload();
  };
  qs("#apply-offset").addEventListener("click", () => rerun({ offset: state.offsetDraft }));
  qs("#auto-offset").addEventListener("click", () => rerun({ reset_offset: true }));
}

function bindCopy(view) {
  const { result, meta } = view;
  qs("#copy").addEventListener("click", async () => {
    const lines = view.visibleIssues().map((i) => `${where(i)} (${fmtTime(i.time)}): ${labelOf(i.type)} – ${shortMsg(i)}`);
    const notes = [...(result.warnings || []).map((w) => `${t("warning")}: ${renderMsg(w)}`),
      ...(result.hints || []).map((h) => `${t("hint")}: ${renderMsg(h)}`)];
    const text = [`${result.title} – ${meta.audio_name}`, ...notes, ...(notes.length ? [""] : []), ...lines].join("\n");
    try { await navigator.clipboard.writeText(text); qs("#copy").textContent = t("copied"); } catch { prompt(t("copyPrompt"), text); }
    setTimeout(() => { const b = qs("#copy"); if (b) b.textContent = t("copy"); }, 1500);
  });
}

/** Bedienelemente verdrahten; gibt eine Aufräumfunktion für globale Listener zurück. */
export function bindControls(view) {
  bindPlayback(view);
  bindToolbar(view);
  bindOffset(view);
  bindCopy(view);

  const onKey = (ev) => {
    if (ev.target.closest("input, select, textarea")) return;
    if (ev.code === "Space") { ev.preventDefault(); if (view.el.audio.paused) view.el.audio.play(); else view.el.audio.pause(); }
    if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
      ev.preventDefault();
      const visible = view.visibleIssues();
      if (!visible.length) return;
      const step = ev.key === "ArrowRight" ? 1 : -1;
      let k = visible.findIndex((i) => i.id === view.state.selected);
      k = k < 0 ? (step > 0 ? 0 : visible.length - 1) : (k + step + visible.length) % visible.length;
      view.select(visible[k].id, true);
    }
  };
  const onResize = () => { view.pianoroll.size(); view.draw(); };
  const redraw = () => view.draw();
  const darkQuery = matchMedia("(prefers-color-scheme: dark)");
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", onResize);
  window.addEventListener("themechange", redraw);
  darkQuery.addEventListener("change", redraw);
  return () => {
    view.el.audio.pause();
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", onResize);
    window.removeEventListener("themechange", redraw);
    darkQuery.removeEventListener("change", redraw);
  };
}
