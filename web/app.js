// Take Check – Oberfläche ohne Build-Schritt: Upload, Analyse-Liste, Pianoroll mit Fehlermarkierungen.

import { LANG, T, fmtBeat, txt } from "./i18n.js";

const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
const tooltip = $("#tooltip");

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const noteName = (m) => `${NOTE_NAMES[m % 12]}${Math.floor(m / 12) - 1}`;

const CATEGORY_COLORS = {
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
const catOf = (type) => TYPE_CATEGORY[type] || "notes";
const labelOf = (type) => T.types[type] || type;
const msgOf = (i) => txt(i.messages) || i.message;
const CHORD_SIZE_RE = /\s*\((Akkord mit|chord of) \d+ (Tönen|notes)[^)]*\)/;
const shortMsg = (i) => msgOf(i).replace(/^[^:]+:\s*/, "").replace(CHORD_SIZE_RE, "");

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmtTime = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const tab = (n) => (n.string ? T.tab(n) : "");

const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* privat/blockiert */ } },
};

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* kein JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

// ---------------------------------------------------------------- Kopfzeile: Sprache und Darstellung

function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

function setupHeader() {
  document.documentElement.lang = LANG;
  $(".tagline").textContent = T.tagline;
  const theme = store.get("tc.theme", "auto");
  applyTheme(theme);
  $("#controls").innerHTML = `
    <label title="${T.language}"><select id="lang-select" aria-label="${T.language}">
      <option value="de">DE</option><option value="en">EN</option></select></label>
    <label title="${T.theme}"><select id="theme-select" aria-label="${T.theme}">
      <option value="auto">◐ ${T.themeAuto}</option><option value="light">☀ ${T.themeLight}</option>
      <option value="dark">☾ ${T.themeDark}</option></select></label>`;
  $("#lang-select").value = LANG;
  $("#theme-select").value = theme;
  $("#lang-select").addEventListener("change", (ev) => { store.set("tc.lang", ev.target.value); location.reload(); });
  $("#theme-select").addEventListener("change", (ev) => {
    store.set("tc.theme", ev.target.value);
    applyTheme(ev.target.value);
    window.dispatchEvent(new Event("themechange"));
  });
}

let cleanup = () => {};
setupHeader();
window.addEventListener("hashchange", route);
route();

function route() {
  cleanup();
  cleanup = () => {};
  tooltip.hidden = true;
  const m = location.hash.match(/^#\/a\/([\w-]+)/);
  if (m) showAnalysis(m[1]);
  else showHome();
}

// ---------------------------------------------------------------- Startseite

async function showHome() {
  app.innerHTML = `
    <section class="card">
      <h2>${T.newAnalysis}</h2>
      <form id="upload" class="upload">
        <div class="form-row files">
          <label class="field"><span class="label">${T.score}</span>
            <input type="file" name="score" accept=".gp,.musicxml,.xml,.mxl,.mid,.midi" required>
            <small>${T.scoreHint}</small></label>
          <label class="field"><span class="label">${T.audio}</span>
            <input type="file" name="audio" accept=".wav,.flac,.aif,.aiff,.mp3,.ogg,.m4a,audio/*" required>
            <small>${T.audioHint}</small></label>
        </div>
        <div class="form-row options">
          <label class="field"><span class="label">${T.tuning}</span>
            <select name="tuning_preset" id="tuning-preset"><option value="">${T.tuningFromScore}</option></select>
            <small>${T.tuningHint}</small></label>
          <label class="field" id="custom-tuning" hidden><span class="label">${T.customTuning}</span>
            <input type="text" name="tuning_custom" placeholder="B1 E2 A2 D3 G3 B3 E4">
            <small>${T.customTuningHint}</small></label>
          <label class="field"><span class="label">${T.profile}</span>
            <select name="profile" id="profile"></select>
            <small>${T.profileHint}</small></label>
          <label class="field narrow"><span class="label">${T.timingTol}</span>
            <input type="number" name="timing_tol_ms" min="5" max="200" step="5" placeholder="30">
            <small>${T.timingTolHint}</small></label>
        </div>
        <div class="form-actions"><span id="upload-msg" class="muted"></span>
          <button class="btn primary" type="submit">${T.analyze}</button></div>
      </form>
    </section>
    <section class="card">
      <h2>${T.previous}</h2>
      <div id="list"><p class="muted">${T.loading}</p></div>
    </section>`;

  const preset = $("#tuning-preset");
  const profileSel = $("#profile");
  try {
    const [{ presets }, profiles] = await Promise.all([api("/api/tunings"), api("/api/profiles")]);
    for (const [name, notes] of Object.entries(presets)) {
      preset.insertAdjacentHTML("beforeend", `<option value="${esc(name)}">${esc(name)} (${notes.map(noteName).join(" ")})</option>`);
    }
    for (const p of profiles) {
      profileSel.insertAdjacentHTML("beforeend", `<option value="${esc(p.id)}" title="${esc(p.description)}">${esc(p.name)}</option>`);
    }
    profileSel.value = store.get("tc.profile", "standard");
    if (!profileSel.value) profileSel.selectedIndex = 0;
  } catch { /* optional */ }
  preset.insertAdjacentHTML("beforeend", `<option value="__custom">${T.tuningCustom}</option>`);
  preset.addEventListener("change", () => { $("#custom-tuning").hidden = preset.value !== "__custom"; });

  $("#upload").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const data = new FormData();
    data.append("score", form.score.files[0]);
    data.append("audio", form.audio.files[0]);
    data.append("tuning", preset.value === "__custom" ? form.tuning_custom.value : preset.value);
    if (form.timing_tol_ms.value) data.append("timing_tol_ms", form.timing_tol_ms.value);
    data.append("profile", profileSel.value || "standard");
    store.set("tc.profile", profileSel.value);
    const btn = form.querySelector("button");
    btn.disabled = true;
    $("#upload-msg").textContent = T.uploading;
    try {
      const { id } = await api("/api/analyses", { method: "POST", body: data });
      location.hash = `#/a/${id}`;
    } catch (e) {
      $("#upload-msg").innerHTML = `<span class="error">${esc(e.message)}</span>`;
      btn.disabled = false;
    }
  });

  let timer;
  const refresh = async () => {
    let items = [];
    try { items = await api("/api/analyses"); } catch (e) { $("#list").innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
    renderList(items);
    if (items.some((i) => i.status === "queued" || i.status === "running")) timer = setTimeout(refresh, 1500);
  };
  cleanup = () => clearTimeout(timer);
  refresh();
}

const stageText = (s) => T.stages[s] || s || T.statusQueued;

function renderList(items) {
  const list = $("#list");
  if (!list) return;
  if (!items.length) { list.innerHTML = `<p class="muted">${T.noAnalyses}</p>`; return; }
  const statusText = (i) => ({
    done: T.statusDone(i),
    error: T.statusError,
    running: `${stageText(i.stage)} (${Math.round((i.progress || 0) * 100)} %)`,
    queued: T.statusQueued,
  }[i.status] || i.status);
  list.innerHTML = `<table class="list"><thead><tr><th>${T.date}</th><th>${T.scoreAudio}</th><th>${T.status}</th><th></th></tr></thead><tbody>
    ${items.map((i) => `<tr>
      <td class="mono">${new Date(i.created * 1000).toLocaleString(T.dateLocale, { dateStyle: "short", timeStyle: "short" })}</td>
      <td><a href="#/a/${i.id}">${esc(i.title || i.score_name)}</a><br><span class="muted">${esc(i.audio_name)}</span></td>
      <td><span class="status"><span class="dot ${i.status}"></span>${esc(statusText(i))}</span></td>
      <td style="text-align:right"><button class="btn small" data-del="${i.id}" ${i.status === "running" || i.status === "queued" ? "disabled" : ""}>${T.delete}</button></td>
    </tr>`).join("")}</tbody></table>`;
  list.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(T.confirmDelete)) return;
    await api(`/api/analyses/${b.dataset.del}`, { method: "DELETE" });
    showHome();
  }));
}

// ---------------------------------------------------------------- Analyse-Ansicht

async function showAnalysis(id) {
  app.innerHTML = `<section class="card"><p class="muted">${T.loading}</p></section>`;
  let timer;
  cleanup = () => clearTimeout(timer);
  const poll = async () => {
    let meta;
    try { meta = await api(`/api/analyses/${id}`); } catch (e) {
      app.innerHTML = `<section class="card"><p class="error">${esc(e.message)}</p><a href="#/">${T.toOverview}</a></section>`;
      return;
    }
    if (meta.status === "done") {
      const [result, peaks] = await Promise.all([api(`/api/analyses/${id}/result`), api(`/api/analyses/${id}/peaks`)]);
      renderAnalysis(id, meta, result, peaks);
      if (meta.outdated) {
        $(".summary-head").insertAdjacentHTML("afterend", `<div class="notice">${T.outdated}
          <button class="btn small primary" id="refresh-analysis">${T.recompute}</button></div>`);
        $("#refresh-analysis").addEventListener("click", async () => {
          await api(`/api/analyses/${id}/rerun`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
          showAnalysis(id);
        });
      }
    } else if (meta.status === "error") {
      app.innerHTML = `<section class="card"><h2>${T.failed}</h2><p class="error">${esc(meta.error)}</p>
        <p class="muted">${esc(meta.score_name)} · ${esc(meta.audio_name)}</p><a href="#/">${T.toOverview}</a></section>`;
    } else {
      app.innerHTML = `<section class="card"><h2>${esc(meta.score_name)} · ${esc(meta.audio_name)}</h2>
        <div class="progress"><div style="width:${Math.round((meta.progress || 0) * 100)}%"></div></div>
        <p class="muted">${esc(stageText(meta.stage))} …</p></section>`;
      timer = setTimeout(poll, 800);
    }
  };
  poll();
}

function renderAnalysis(id, meta, result, peaks) {
  const state = {
    pps: store.get("tc.pps", 120),
    timingTol: Math.round((result.options.timing_tol || 0.03) * 1000),
    minConf: store.get("tc.minConf", 0.5),
    cats: new Set(store.get("tc.cats", Object.keys(CATEGORY_COLORS))),
    selected: null,
    preroll: store.get("tc.preroll", "bar1"),
    // Anschlagsrichtung nur, wenn das Profil sie freigibt (Erkennung nicht für alle Akkorde zuverlässig)
    strumEnabled: Boolean(result.display?.strum_direction),
    showStrum: store.get("tc.showStrum", true),
    offsetDraft: result.offset,
  };
  // neu hinzugekommene Kategorien sind auch bei gespeicherten Filtern zunächst sichtbar
  const knownCats = new Set(store.get("tc.knownCats", Object.keys(CATEGORY_COLORS)));
  for (const k of Object.keys(CATEGORY_COLORS)) if (!knownCats.has(k)) state.cats.add(k);
  store.set("tc.knownCats", Object.keys(CATEGORY_COLORS));
  const notesById = new Map(result.notes.map((n) => [n.id, n]));
  const detById = new Map(result.detected.map((d) => [d.id, d]));
  const warnings = result.warnings || [];
  const hints = result.hints || [];

  const tuningText = result.tuning ? result.tuning.map(noteName).join(" ") : T.fromNotation;
  app.innerHTML = `
    <section class="card">
      <div class="summary-head">
        <h1>${esc(result.title)}</h1>
        <span class="muted">${esc(meta.score_name)} · ${esc(meta.audio_name)}${result.profile ? ` · ${T.profile}: ${esc(result.profile.name)}` : ""}</span>
        <a href="#/">${T.allAnalyses}</a>
      </div>
      <div class="stats" id="stats"></div>
      ${warnings.length ? `<ul class="warnings">${warnings.map((w) => `<li>${esc(txt(w))}</li>`).join("")}</ul>` : ""}
      ${hints.length ? `<ul class="hints">${hints.map((h) => `<li>${esc(txt(h))}</li>`).join("")}</ul>` : ""}
      <div class="controls-row">
        <div class="group">${T.offset} <span class="mono" id="offset">${result.offset.toFixed(3)} s</span>
          <button class="btn small" data-off="-0.01">−10 ms</button><button class="btn small" data-off="0.01">+10 ms</button>
          <button class="btn small" id="apply-offset" disabled>${T.recompute}</button>
          <button class="btn small" id="auto-offset" title="${T.autoTitle}">${T.auto}</button></div>
        <div class="group">${T.tuning} <span class="mono">${esc(tuningText)}</span>${result.tuning_cents != null ? `<span class="muted">(${result.tuning_cents >= 0 ? "+" : ""}${result.tuning_cents} ${T.cents})</span>` : ""}</div>
      </div>
    </section>
    <div class="toolbar">
      <div class="group"><button class="btn play" id="play" title="${T.play}">▶</button>
        <span class="mono" id="clock">0:00.0</span></div>
      <label class="group">${T.zoom} <input type="range" id="zoom" min="30" max="600" step="10" value="${state.pps}"></label>
      <label class="group">${T.timingTol} <input type="range" id="tol" min="10" max="120" step="5" value="${state.timingTol}"><span class="mono" id="tol-v">${state.timingTol} ms</span></label>
      ${state.strumEnabled ? `<label class="group" title="${T.strumTitle}"><input type="checkbox" id="strum" ${state.showStrum ? "checked" : ""}> ${T.strum}</label>` : ""}
      <label class="group" title="${T.prerollTitle}">${T.preroll}
        <select id="preroll">
          <option value="0">0 s</option><option value="0.5">0.5 s</option><option value="1">1 s</option>
          <option value="bar1">${T.bar1}</option><option value="bar2">${T.bar2}</option>
        </select></label>
      <label class="group" title="${T.confidenceTitle}">${T.confidence}
        <input type="range" id="conf" min="0" max="0.95" step="0.05" value="${state.minConf}"><span id="conf-v"></span></label>
    </div>
    <div class="workspace">
      <div class="viewer">
        <div class="scroll" id="scroll"><div class="spacer" id="spacer"></div>
          <canvas class="sticky" id="roll"></canvas><canvas class="sticky" id="wave"></canvas></div>
        <div class="legend">
          <span><i></i>${T.legScore}</span>
          <span><i style="background:var(--det);border-color:var(--det);height:4px"></i>${T.legDetected}</span>
          <span><i style="border-style:dashed;border-color:var(--c-notes)"></i>${T.legMissing}</span>
          <span><i style="border-style:dashed;border-color:var(--muted)"></i>${T.legOmitted}</span>
          <span><i style="border-style:dotted"></i>${T.legUnchecked}</span>
          <span><i style="border-bottom:3px solid var(--c-pm)"></i>Palm Mute</span>
          <span><i style="background:var(--c-stops);opacity:.35;border-color:var(--c-stops)"></i>${T.legRest}</span>
          ${state.strumEnabled ? `<span><b style="color:var(--strum-down)">↓</b> ${T.legDown} · <b style="color:var(--strum-up)">↑</b> ${T.legUp} · <b class="muted">·</b> ${T.legUnclear}</span>` : ""}
          <span>◇ ${T.legHarm}</span><span>× Dead Note</span><span>⌒ ${T.legLegato}</span>
          <span><i style="border:0;border-top:2px dashed var(--c-bend);border-radius:0;height:2px"></i> / <i style="border:0;border-top:2px solid var(--c-bend);border-radius:0;height:2px"></i>${T.legBend}</span>
          <span class="muted">${T.keys}</span>
        </div>
      </div>
      <aside class="issues">
        <div class="issues-head"><div id="issue-count"></div><button class="btn small" id="copy" title="${T.copyTitle}">${T.copy}</button></div>
        <div class="issues-list" id="issues"></div>
      </aside>
    </div>
    <audio id="audio" preload="auto" src="/api/analyses/${id}/audio"></audio>`;

  const audio = $("#audio");
  const scroll = $("#scroll");
  const spacer = $("#spacer");
  const roll = $("#roll");
  const wave = $("#wave");
  const ROLL_H = 440, WAVE_H = 80, RULER = 30;

  // Tonhöhenbereich nach der Vorlage; gemeldete Töne in der Nähe dazunehmen, weit entfernte Ausreißer
  // werden am Rand als Pfeil angedeutet statt den Bereich aufzublähen
  const scorePitches = result.notes.flatMap((n) => [n.pitch, n.pitch + Math.ceil(Math.max(0, ...(n.bend || [[0, 0]]).map((b) => b[1])))]);
  let pMin = Math.min(...scorePitches) - 3, pMax = Math.max(...scorePitches) + 3;
  for (const p of result.issues.map((i) => i.played_pitch).filter((p) => p != null)) {
    if (p < pMin && p >= pMin - 7) pMin = p - 1;
    if (p > pMax && p <= pMax + 7) pMax = p + 1;
  }
  const duration = Math.max(result.duration, peaks.duration || 0);

  // ---- Akkordkontext: alle Vorlagennoten mit demselben Anschlag
  const chordOf = new Map();
  {
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
  }
  const CHORD_MARK = { ok: "✓", missing: "✗", omitted: T.omittedMark, unchecked: "–", dead: "×" };
  const strumText = (st) => !st ? "" : st.dir === "down" ? T.strumDown(Math.round(st.spread_ms))
    : st.dir === "up" ? T.strumUp(Math.round(st.spread_ms)) : T.strumUnclear;
  function chordText(n) {
    const group = chordOf.get(n.id) || [n];
    if (group.length < 2) return "";
    const st = state.strumEnabled ? group.find((m) => m.strum)?.strum : null;
    return `${strumText(st) ? strumText(st) + " · " : ""}${T.chord}: ` + group.map((m) => {
      const mark = m.status === "wrong_pitch" ? `→ ${noteName(m.played_pitch)}` : (m.status === "ok" && m.weak ? "✓?" : CHORD_MARK[m.status] || m.status);
      const name = noteName(m.pitch);
      return m.id === n.id ? `<b>${name} ${mark}</b>` : `${name} ${mark}`;
    }).join(" · ");
  }
  function issueDetail(i) {
    const n = i.note_id != null ? notesById.get(i.note_id) : null;
    if (n) return [tab(n), chordText(n)].filter(Boolean).join(" · ");
    const d = i.det_id != null ? detById.get(i.det_id) : null;
    return d ? T.detected(fmtTime(d.onset), Math.round(d.duration * 1000)) : "";
  }

  // ---- Befunde (Timing clientseitig gegen den Groove neu berechnet, damit der Regler ohne Neuanalyse wirkt)
  let issues = [];
  function computeIssues() {
    const tol = state.timingTol / 1000;
    const base = result.issues.filter((i) => i.type !== "early" && i.type !== "late");
    const timing = [];
    for (const n of result.notes) {
      if (n.status !== "ok" || n.weak || n.delta_ms == null) continue;
      const group = chordOf.get(n.id) || [n];
      const isChord = group.length > 1;
      // Akkorde: nur der zuerst angeschlagene Ton zählt – die übrigen Saiten folgen je nach Up-/Downstroke
      if (isChord && !n.chord_lead) continue;
      const groove = (n.groove_ms ?? 0) / 1000;
      const dt = (isChord ? n.chord_delta_ms : n.delta_ms) / 1000 - groove;
      const t = (n.legato || n.harmonic) ? tol * 1.5 : tol;
      if (Math.abs(dt) <= t) continue;
      const arrow = state.strumEnabled && isChord && n.strum?.dir ? (n.strum.dir === "down" ? ", ↓" : ", ↑") : "";
      const ctx = Math.abs(groove) >= 0.008 ? `, ${T.grooveHere} ${groove > 0 ? "+" : ""}${Math.round(groove * 1000)} ms` : "";
      const ms = `${Math.round(Math.abs(dt) * 1000)} ms`;
      const head = isChord ? (dt > 0 ? T.chordLate : T.chordEarly) : (dt > 0 ? T.late : T.early);
      const what = isChord ? group.map((m) => noteName(m.pitch)).join("·") + arrow : noteName(n.pitch);
      timing.push({
        id: `t${n.id}`, type: dt > 0 ? "late" : "early", time: n.onset + dt + groove, bar: n.bar, occurrence: n.occurrence,
        beat: n.beat, note_id: n.id, det_id: n.det_id, confidence: Math.abs(dt) > 2 * t ? 0.9 : 0.6,
        message: `${head}: ${ms} (${what}${ctx})`, delta_ms: Math.round(dt * 1000),
      });
    }
    issues = base.concat(timing).sort((a, b) => a.time - b.time);
  }
  const confLabel = (v) => `${v < 0.35 ? T.confAll : v < 0.65 ? T.confBalanced : T.confSure} (${T.from} ${v.toFixed(2)})`;
  const visibleIssues = () => issues.filter((i) => i.confidence >= state.minConf && state.cats.has(catOf(i.type)));

  function renderStats() {
    const vis = visibleIssues();
    const s = result.summary;
    const counts = {};
    for (const i of issues.filter((i) => i.confidence >= state.minConf)) counts[catOf(i.type)] = (counts[catOf(i.type)] || 0) + 1;
    const noteIssues = new Set(vis.filter((i) => i.note_id != null).map((i) => i.note_id));
    const ok = result.notes.filter((n) => !["dead", "unchecked", "omitted"].includes(n.status) && !noteIssues.has(n.id)).length;
    $("#stats").innerHTML = `<span class="chip static"><b>${ok}/${s.notes_checked}</b>&nbsp;${T.notesOk}</span>` +
      Object.entries(CATEGORY_COLORS).map(([k, color]) => `<span class="chip ${state.cats.has(k) ? "" : "off"}" data-cat="${k}">
        <span class="sw" style="background:var(${color})"></span>${T.cat[k]} <b>${counts[k] || 0}</b></span>`).join("");
    $("#stats").querySelectorAll("[data-cat]").forEach((el) => el.addEventListener("click", () => {
      const k = el.dataset.cat;
      state.cats.has(k) ? state.cats.delete(k) : state.cats.add(k);
      store.set("tc.cats", [...state.cats]);
      refreshAll();
    }));
  }

  function renderIssues() {
    const vis = visibleIssues();
    const hidden = issues.filter((i) => i.confidence < state.minConf && state.cats.has(catOf(i.type))).length;
    $("#issue-count").innerHTML = `<b>${T.findings(vis.length)}</b>` +
      (hidden ? `<div class="sub">${T.hiddenUnsure(hidden)} · <a href="#" id="show-all">${T.showAll}</a></div>` : "");
    $("#show-all")?.addEventListener("click", (ev) => { ev.preventDefault(); setConf(0); });
    const list = $("#issues");
    if (!vis.length) { list.innerHTML = `<div class="empty">${T.noFindings}</div>`; return; }
    list.innerHTML = vis.map((i) => `<div class="issue ${state.selected === i.id ? "sel" : ""}" data-id="${i.id}">
      <span class="bar" style="background:var(${CATEGORY_COLORS[catOf(i.type)]})"></span>
      <div><div class="where"><span>${T.where(i)} · ${fmtTime(i.time)}</span>
        <span title="${T.confTitle(i.confidence.toFixed(2))}"><span class="conf"><b style="width:${i.confidence * 100}%"></b></span></span></div>
        <div class="msg"><b>${esc(labelOf(i.type))}</b> – ${esc(shortMsg(i))}</div>
        ${issueDetail(i) ? `<div class="detail">${issueDetail(i)}</div>` : ""}</div></div>`).join("");
    list.querySelectorAll(".issue").forEach((el) => el.addEventListener("click", () => selectIssue(el.dataset.id, true)));
  }

  function prerollStart(t) {
    const p = state.preroll;
    if (!p.startsWith("bar")) return Math.max(t - Number(p), 0);
    const k = result.bars.findIndex((b) => b.start <= t + 1e-6 && t < b.end);
    const back = Number(p.slice(3));
    if (k < 0) return Math.max(t - 2 * back, 0);
    // Taktanfang des Befund-Takts minus (Vorlauf − 1) weitere Takte; liegt der Befund am Taktanfang, einen Takt mehr
    const idx = Math.max(k - back + (t - result.bars[k].start > 0.05 ? 1 : 0), 0);
    return result.bars[idx].start;
  }

  function selectIssue(issueId, play) {
    const i = issues.find((x) => String(x.id) === String(issueId));
    if (!i) return;
    state.selected = i.id;
    const from = prerollStart(i.time);
    const W = roll.clientWidth;
    // Befund bei ~40 % der Breite; wenn möglich auch den Startpunkt der Wiedergabe sichtbar halten
    let left = i.time * state.pps - W * 0.4;
    if (from * state.pps < left + W * 0.03 && i.time * state.pps - from * state.pps < W * 0.8) left = from * state.pps - W * 0.05;
    scroll.scrollLeft = Math.max(left, 0);
    audio.currentTime = from;
    if (play) audio.play();
    renderIssues();
    $(`.issue[data-id="${CSS.escape(String(i.id))}"]`)?.scrollIntoView({ block: "nearest" });
    draw();
  }

  // ---- Zeichnen
  function sizeCanvases() {
    const w = scroll.clientWidth, dpr = window.devicePixelRatio || 1;
    spacer.style.width = `${Math.ceil(duration * state.pps)}px`;
    for (const [c, h] of [[roll, ROLL_H], [wave, WAVE_H]]) {
      c.width = Math.floor(w * dpr); c.height = Math.floor(h * dpr);
      c.style.width = `${w}px`; c.style.height = `${h}px`;
      c.style.marginTop = c === roll ? "-1px" : "0";
    }
  }

  let raf = 0;
  const draw = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; drawRoll(); drawWave(); }); };

  function drawRoll() {
    const ctx = roll.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const W = roll.width / dpr, H = ROLL_H;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const t0 = scroll.scrollLeft / state.pps, t1 = t0 + W / state.pps;
    const row = (H - RULER) / (pMax - pMin + 1);
    const X = (t) => (t - t0) * state.pps;
    const Y = (p) => RULER + (pMax - p) * row;
    const colors = Object.fromEntries(Object.entries(CATEGORY_COLORS).map(([k, c]) => [k, css(c)]));

    // Zeilen und Oktaven
    for (let p = pMin; p <= pMax; p++) {
      if ([1, 3, 6, 8, 10].includes(p % 12)) { ctx.fillStyle = css("--row-alt"); ctx.fillRect(0, Y(p), W, row); }
      if (p % 12 === 0) {
        ctx.fillStyle = css("--grid"); ctx.fillRect(0, Y(p) + row - 0.5, W, 1);
        ctx.fillStyle = css("--muted"); ctx.font = "10px system-ui"; ctx.fillText(noteName(p), 4, Y(p) + row - 2);
      }
    }
    // Takte mit Fehlerdichte
    const vis = visibleIssues();
    ctx.font = "11px system-ui";
    for (const b of result.bars) {
      if (b.end < t0 || b.start > t1) continue;
      const weight = vis.filter((i) => i.time >= b.start && i.time < b.end).reduce((s, i) => s + i.confidence, 0);
      ctx.fillStyle = `rgba(${css("--heat")}, ${Math.min(weight / 3, 1) * 0.55})`;
      ctx.fillRect(X(b.start), 0, X(b.end) - X(b.start), RULER - 12);
      ctx.fillStyle = css("--grid-strong"); ctx.fillRect(Math.round(X(b.start)), 0, 1, H);
      ctx.fillStyle = css("--text");
      ctx.fillText(`${b.number}${b.occurrence > 1 ? ` (${b.occurrence}.)` : ""}`, X(b.start) + 4, 12);
      const beat = (b.end - b.start) / b.beats;
      ctx.fillStyle = css("--grid");
      for (let k = 1; k < b.beats; k++) ctx.fillRect(Math.round(X(b.start + k * beat)), RULER - 12, 1, H);
    }
    ctx.fillStyle = css("--grid-strong"); ctx.fillRect(0, RULER - 12, W, 1);

    // nachklingende Pausen: Bereich hinterlegen
    for (const i of vis) {
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
    for (const i of vis) if (i.note_id != null && !issueColorByNote.has(i.note_id)) issueColorByNote.set(i.note_id, colors[catOf(i.type)]);

    // erkannte Noten
    for (const d of result.detected) {
      if (d.onset + d.duration < t0 || d.onset > t1) continue;
      const extra = vis.find((i) => i.type === "extra" && i.det_id === d.id);
      if (!d.matched && !extra) continue;
      if (d.pitch < pMin || d.pitch > pMax) {
        if (extra) {  // außerhalb des Bereichs: Pfeil am Rand mit Notenname
          const above = d.pitch > pMax, x = X(d.onset), y = above ? RULER + 1 : H - 1;
          ctx.fillStyle = colors.notes; ctx.font = "bold 10px system-ui";
          ctx.fillText(`${above ? "▲" : "▼"} ${noteName(d.pitch)}`, x, above ? y + 10 : y - 2);
        }
        continue;
      }
      ctx.fillStyle = extra ? colors.notes : css("--det");
      ctx.globalAlpha = extra ? 0.9 : 0.7;
      ctx.fillRect(X(d.onset), Y(d.pitch) + row * 0.32, Math.max(d.duration * state.pps, 2), Math.max(row * 0.36, 2));
      ctx.globalAlpha = 1;
    }
    // Vorlagennoten
    const okColor = css("--note-ok");
    const selNote = state.selected != null ? issues.find((i) => i.id === state.selected)?.note_id : null;
    for (const n of result.notes) {
      if (n.onset + n.duration < t0 || n.onset > t1) continue;
      const x = X(n.onset), y = Y(n.pitch), w = Math.max(n.duration * state.pps, 3), h = Math.max(row - 1, 2);
      const color = issueColorByNote.get(n.id) || okColor;
      ctx.strokeStyle = color; ctx.lineWidth = selNote === n.id ? 2.5 : 1.3;
      const absent = n.status === "missing" || n.status === "omitted";
      if (n.status === "omitted" && !issueColorByNote.has(n.id)) ctx.strokeStyle = css("--muted");
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
        n.bend.forEach(([bt, s], k) => { const px = X(n.onset + bt), py = Y(n.pitch + s) + row / 2; k ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
        ctx.stroke(); ctx.setLineDash([]);
        if (n.contour) {
          ctx.lineWidth = 2; ctx.beginPath();
          n.contour.forEach(([ct, s], k) => { const px = X(ct), py = Y(n.pitch + s) + row / 2; k ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
          ctx.stroke();
        }
      }
    }
    // Anschlagrichtung: Pfeil über dem Akkord; unklar = kleiner Punkt
    if (state.strumEnabled && state.showStrum) {
      const down = css("--strum-down"), up = css("--strum-up");
      let lastX = -1e9;
      for (const n of result.notes) {
        if (!n.chord_lead || !n.strum || n.onset < t0 - 0.2 || n.onset > t1 + 0.2) continue;
        const group = chordOf.get(n.id) || [n];
        const top = Y(group[group.length - 1].pitch), bottom = Y(group[0].pitch) + row;
        const x = X(n.strum.attack ?? n.onset);
        if (x - lastX < 9) continue;  // zu dicht: Pfeile würden sich überlagern
        lastX = x;
        const dir = n.strum.dir;
        if (!dir) { ctx.fillStyle = css("--muted"); ctx.globalAlpha = 0.5; ctx.fillRect(x - 1.5, top - 9, 3, 3); ctx.globalAlpha = 1; continue; }
        // Pfeilrichtung wie in Akkordschreibweisen: ↓ = Downstroke (tiefe Saite zuerst), ↑ = Upstroke
        const len = Math.min(Math.max(bottom - top, 14), 60);
        const y0 = top - 6 - len, y1 = top - 6;
        ctx.strokeStyle = dir === "down" ? down : up; ctx.fillStyle = ctx.strokeStyle; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(x, dir === "down" ? y0 : y1); ctx.lineTo(x, dir === "down" ? y1 - 4 : y0 + 4); ctx.stroke();
        const tip = dir === "down" ? y1 : y0, back = dir === "down" ? -6 : 6;
        ctx.beginPath(); ctx.moveTo(x, tip); ctx.lineTo(x - 4, tip + back); ctx.lineTo(x + 4, tip + back); ctx.fill();
      }
    }

    // Befund-Markierungen
    for (const i of vis) {
      if (i.time < t0 - 1 || i.time > t1 + 1) continue;
      const x = X(i.time);
      ctx.fillStyle = colors[catOf(i.type)];
      ctx.beginPath(); ctx.moveTo(x - 5, RULER - 11); ctx.lineTo(x + 5, RULER - 11); ctx.lineTo(x, RULER - 3); ctx.fill();
      if (i.id === state.selected) { ctx.globalAlpha = 0.35; ctx.fillRect(x - 1, RULER - 12, 2, H); ctx.globalAlpha = 1; }
    }
    // gewählter Befund: Spalte über die ganze Höhe + kräftiger Rahmen um die betroffene Note
    const sel = state.selected != null ? issues.find((i) => i.id === state.selected) : null;
    if (sel) {
      const n = sel.note_id != null ? notesById.get(sel.note_id) : null;
      const d = sel.det_id != null ? detById.get(sel.det_id) : null;
      const accent = css("--accent");
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
    // Abspielposition
    const cx = X(audio.currentTime);
    if (cx >= 0 && cx <= W) { ctx.fillStyle = css("--cursor"); ctx.fillRect(Math.round(cx), 0, 1.5, H); }
  }

  function drawWave() {
    const ctx = wave.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const W = wave.width / dpr, H = WAVE_H;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = css("--grid"); ctx.fillRect(0, 0, W, 1);
    const t0 = scroll.scrollLeft / state.pps;
    const per = peaks.per_second, data = peaks.peaks;
    ctx.fillStyle = css("--wave");
    for (let x = 0; x < W; x++) {
      const a = Math.floor((t0 + x / state.pps) * per), b = Math.max(Math.floor((t0 + (x + 1) / state.pps) * per), a + 1);
      let lo = 0, hi = 0;
      for (let k = a; k < b && k < data.length; k++) { if (data[k][0] < lo) lo = data[k][0]; if (data[k][1] > hi) hi = data[k][1]; }
      ctx.fillRect(x, H / 2 - hi * H * 0.48, 1, Math.max((hi - lo) * H * 0.48, 0.5));
    }
    const cx = (audio.currentTime - t0) * state.pps;
    if (cx >= 0 && cx <= W) { ctx.fillStyle = css("--cursor"); ctx.fillRect(Math.round(cx), 0, 1.5, H); }
  }

  // ---- Interaktion
  const noteOfDet = new Map(result.notes.filter((n) => n.det_id != null).map((n) => [n.det_id, n]));
  function noteAt(ev) {
    const rect = roll.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    const t = scroll.scrollLeft / state.pps + mx / state.pps;
    const row = (ROLL_H - RULER) / (pMax - pMin + 1);
    const pitch = pMax - Math.floor((my - RULER) / row);
    const pad = 4 / state.pps;
    const hit = result.notes.find((n) => n.pitch === pitch && t >= n.onset - 0.02 && t <= n.onset + Math.max(n.duration, pad));
    // erkannte Töne: zusätzliche (rot) haben Vorrang, sonst zugeordnete (grau); dünne Linien bei enger
    // Darstellung auch eine Zeile daneben treffen, wenn dort sonst nichts liegt
    const vis = visibleIssues();
    const near = row < 8 ? [pitch, pitch + 1, pitch - 1] : [pitch];
    const detsAt = (p) => result.detected.filter((d) => d.pitch === p && t >= d.onset - pad && t <= d.onset + Math.max(d.duration, pad));
    const dets = hit ? detsAt(pitch) : (near.map(detsAt).find((ds) => ds.length) || []);
    const extraIssue = dets.map((d) => vis.find((i) => i.type === "extra" && i.det_id === d.id)).find(Boolean);
    const det = extraIssue ? detById.get(extraIssue.det_id) : dets.find((d) => d.matched);
    const rest = vis.find((i) => i.type === "rest_ringing" && i.rest_end != null && t >= i.time && t <= i.rest_end);
    const marker = my < RULER ? vis.find((i) => Math.abs(i.time - t) * state.pps <= 6) : null;
    const bar = my < RULER ? result.bars.find((b) => t >= b.start && t < b.end) : null;
    return { t, my, hit, det, extraIssue, rest, marker, bar };
  }
  const placeTooltip = (ev) => {
    tooltip.hidden = false;
    const x = Math.min(ev.clientX + 14, window.innerWidth - tooltip.offsetWidth - 8);
    const y = Math.min(ev.clientY + 14, window.innerHeight - tooltip.offsetHeight - 8);
    tooltip.style.left = `${x}px`; tooltip.style.top = `${y}px`;
  };
  const issueLine = (i) => `<div class="t-issue" style="color:var(${CATEGORY_COLORS[catOf(i.type)]})">● ${esc(msgOf(i))}</div>`;
  roll.addEventListener("mousemove", (ev) => {
    const { hit, my, det, extraIssue, rest, marker, bar } = noteAt(ev);
    if (!marker && bar) {
      const n = visibleIssues().filter((i) => i.time >= bar.start && i.time < bar.end).length;
      tooltip.innerHTML = `<b>${T.barTitle(bar)}</b> · ${bar.beats}/${bar.beat_type} · ${fmtTime(bar.start)}
        <br><span class="muted">${T.barFindings(n)}</span>`;
      placeTooltip(ev); return;
    }
    if (marker) {
      tooltip.innerHTML = `<b>${esc(labelOf(marker.type))}</b> · ${T.where(marker)}${issueLine(marker)}
        <span class="muted">${T.confShort} ${marker.confidence.toFixed(2)}</span>`;
      placeTooltip(ev); return;
    }
    if (!hit && extraIssue && det) {
      tooltip.innerHTML = `<b>${T.extraTitle}</b><br><b>${noteName(det.pitch)}</b> · ${T.where(extraIssue)} · ${fmtTime(det.onset)}
        <br><span class="muted">${T.duration} ${Math.round(det.duration * 1000)} ms · ${T.confShort} ${extraIssue.confidence.toFixed(2)}</span>
        ${issueLine(extraIssue)}<div class="muted t-explain">${T.extraExplain}</div>`;
      placeTooltip(ev); return;
    }
    if (!hit && det) {
      const n = noteOfDet.get(det.id);
      const rel = n ? (n.status === "wrong_pitch" ? T.playedInstead(noteName(det.pitch), noteName(n.pitch))
        : `${T.belongsTo} ${noteName(n.pitch)} (${T.where(n)})`) : "";
      tooltip.innerHTML = `<b>${T.detTitle}: ${noteName(det.pitch)}</b> · ${fmtTime(det.onset)}
        <br><span class="muted">${T.duration} ${Math.round(det.duration * 1000)} ms${rel ? ` · ${rel}` : ""}</span>`;
      placeTooltip(ev); return;
    }
    if (!hit && rest) {
      tooltip.innerHTML = `<b>${T.restTitle}</b> · ${T.where(rest)} · ${fmtTime(rest.time)}–${fmtTime(rest.rest_end)}
        ${issueLine(rest)}<div class="muted t-explain">${T.restExplain}</div>`;
      placeTooltip(ev); return;
    }
    if (!hit || my < RULER) { tooltip.hidden = true; return; }
    const nIssues = issues.filter((i) => i.note_id === hit.id);
    const tech = [hit.palm_mute && "Palm Mute", hit.legato && "Hammer-on/Pull-off", hit.slide && "Slide",
      hit.harmonic && `${T.legHarm} (${hit.harmonic}${hit.fretted_pitch ? `, ${T.techFretted} ${noteName(hit.fretted_pitch)}` : ""})`,
      hit.bend && `Bend +${Math.max(...hit.bend.map((b) => b[1]))} ${T.semitones}`, hit.vibrato && "Vibrato", hit.dead && "Dead Note"].filter(Boolean);
    const status = hit.status === "ok" ? (hit.weak ? T.st.weak : T.st.ok)
      : hit.status === "wrong_pitch" ? `${T.st.wrong_pitch}: ${noteName(hit.played_pitch)}` : T.st[hit.status] || hit.status;
    tooltip.innerHTML = `<b>${noteName(hit.pitch)}</b> · ${T.where(hit)}${hit.string ? ` · ${T.tab(hit)}` : ""}
      ${tech.length ? `<br>${tech.join(" · ")}` : ""}
      ${chordText(hit) ? `<br>${chordText(hit)}` : ""}
      <br><span class="muted">${status}${hit.delta_ms != null ? ` · ${hit.delta_ms > 0 ? "+" : ""}${hit.delta_ms} ms` : ""}</span>
      ${nIssues.map(issueLine).join("")}`;
    placeTooltip(ev);
  });
  roll.addEventListener("mouseleave", () => { tooltip.hidden = true; });
  const seekClick = (ev) => {
    const { t, hit, extraIssue, rest, marker } = noteAt(ev);
    const target = hit ? visibleIssues().find((x) => x.note_id === hit.id) : marker || extraIssue || rest;
    if (target) { selectIssue(target.id, false); return; }
    audio.currentTime = Math.max(0, Math.min(t, duration));
    draw();
  };
  roll.addEventListener("click", seekClick);
  wave.addEventListener("click", seekClick);
  scroll.addEventListener("scroll", draw, { passive: true });

  const playBtn = $("#play");
  playBtn.addEventListener("click", () => (audio.paused ? audio.play() : audio.pause()));
  audio.addEventListener("play", () => { playBtn.textContent = "❚❚"; tick(); });
  audio.addEventListener("pause", () => { playBtn.textContent = "▶"; draw(); });
  audio.addEventListener("seeked", draw);
  function tick() {
    if (audio.paused) return;
    // nur mitscrollen, wenn der Cursor rechts aus dem Bild läuft – sonst bleibt die Ansicht auf dem Befund
    const W = roll.clientWidth, x = audio.currentTime * state.pps - scroll.scrollLeft;
    if (x > W * 0.9) scroll.scrollLeft = audio.currentTime * state.pps - W * 0.1;
    $("#clock").textContent = fmtTime(audio.currentTime);
    draw();
    requestAnimationFrame(tick);
  }

  $("#zoom").addEventListener("input", (ev) => {
    const center = (scroll.scrollLeft + roll.clientWidth / 2) / state.pps;
    state.pps = +ev.target.value; store.set("tc.pps", state.pps);
    sizeCanvases();
    scroll.scrollLeft = center * state.pps - roll.clientWidth / 2;
    draw();
  });
  $("#strum")?.addEventListener("change", (ev) => { state.showStrum = ev.target.checked; store.set("tc.showStrum", state.showStrum); draw(); });
  $("#preroll").value = state.preroll;
  $("#preroll").addEventListener("change", (ev) => { state.preroll = ev.target.value; store.set("tc.preroll", state.preroll); });
  $("#tol").addEventListener("input", (ev) => { state.timingTol = +ev.target.value; $("#tol-v").textContent = `${state.timingTol} ms`; refreshAll(); });
  function setConf(v) {
    state.minConf = v; store.set("tc.minConf", v);
    $("#conf").value = v; $("#conf-v").textContent = confLabel(v); refreshAll();
  }
  $("#conf-v").textContent = confLabel(state.minConf);
  $("#conf").addEventListener("input", (ev) => setConf(+ev.target.value));

  document.querySelectorAll("[data-off]").forEach((b) => b.addEventListener("click", () => {
    state.offsetDraft = Math.round((state.offsetDraft + +b.dataset.off) * 1000) / 1000;
    $("#offset").textContent = `${state.offsetDraft.toFixed(3)} s${state.offsetDraft !== result.offset ? ` (${T.changed})` : ""}`;
    $("#apply-offset").disabled = state.offsetDraft === result.offset;
  }));
  const rerun = async (body) => {
    await api(`/api/analyses/${id}/rerun`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    audio.pause();
    showAnalysis(id);
  };
  $("#apply-offset").addEventListener("click", () => rerun({ offset: state.offsetDraft }));
  $("#auto-offset").addEventListener("click", () => rerun({ reset_offset: true }));

  $("#copy").addEventListener("click", async () => {
    const lines = visibleIssues().map((i) => `${T.where(i)} (${fmtTime(i.time)}): ${labelOf(i.type)} – ${shortMsg(i)}`);
    const notes = [...warnings.map((w) => `${T.warning}: ${txt(w)}`), ...hints.map((h) => `${T.hint}: ${txt(h)}`)];
    const text = [`${result.title} – ${meta.audio_name}`, ...notes, ...(notes.length ? [""] : []), ...lines].join("\n");
    try { await navigator.clipboard.writeText(text); $("#copy").textContent = T.copied; }
    catch { prompt(T.copyPrompt, text); }
    setTimeout(() => { const b = $("#copy"); if (b) b.textContent = T.copy; }, 1500);
  });

  const onKey = (ev) => {
    if (ev.target.closest("input, select, textarea")) return;
    if (ev.code === "Space") { ev.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
    if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
      ev.preventDefault();
      const vis = visibleIssues();
      if (!vis.length) return;
      let k = vis.findIndex((i) => i.id === state.selected);
      k = k < 0 ? (ev.key === "ArrowRight" ? 0 : vis.length - 1) : (k + (ev.key === "ArrowRight" ? 1 : -1) + vis.length) % vis.length;
      selectIssue(vis[k].id, true);
    }
  };
  document.addEventListener("keydown", onKey);
  const onResize = () => { sizeCanvases(); draw(); };
  window.addEventListener("resize", onResize);
  const mq = matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", draw);
  window.addEventListener("themechange", draw);
  cleanup = () => {
    audio.pause();
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", onResize);
    window.removeEventListener("themechange", draw);
    mq.removeEventListener("change", draw);
  };

  function refreshAll() { computeIssues(); renderStats(); renderIssues(); draw(); }
  sizeCanvases();
  refreshAll();
}
