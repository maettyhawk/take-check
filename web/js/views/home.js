// Startseite: neue Analyse hochladen, bisherige Analysen auflisten.

import { api } from "../core/api.js";
import { esc, qs, qsa } from "../core/dom.js";
import { noteName } from "../core/format.js";
import { dateLocale, stageText, t } from "../core/i18n.js";
import { store } from "../core/store.js";

const SCORE_ACCEPT = ".gp,.musicxml,.xml,.mxl,.mid,.midi";
const AUDIO_ACCEPT = ".wav,.flac,.aif,.aiff,.mp3,.ogg,.m4a,audio/*";

const template = () => `
  <section class="card">
    <h2>${t("newAnalysis")}</h2>
    <form id="upload" class="upload">
      <div class="form-row files">
        <label class="field"><span class="label">${t("score")}</span>
          <input type="file" name="score" accept="${SCORE_ACCEPT}" required>
          <small>${t("scoreHint")}</small></label>
        <label class="field"><span class="label">${t("audio")}</span>
          <input type="file" name="audio" accept="${AUDIO_ACCEPT}" required>
          <small>${t("audioHint")}</small></label>
      </div>
      <div class="form-row options">
        <label class="field"><span class="label">${t("tuning")}</span>
          <select name="tuning_preset" id="tuning-preset"><option value="">${t("tuningFromScore")}</option></select>
          <small>${t("tuningHint")}</small></label>
        <label class="field" id="custom-tuning" hidden><span class="label">${t("customTuning")}</span>
          <input type="text" name="tuning_custom" placeholder="B1 E2 A2 D3 G3 B3 E4">
          <small>${t("customTuningHint")}</small></label>
        <label class="field"><span class="label">${t("profile")}</span>
          <select name="profile" id="profile"></select>
          <small>${t("profileHint")}</small></label>
        <label class="field narrow"><span class="label">${t("timingTol")}</span>
          <input type="number" name="timing_tol_ms" min="5" max="200" step="5" placeholder="30">
          <small>${t("timingTolHint")}</small></label>
      </div>
      <div class="form-actions"><span id="upload-msg" class="muted"></span>
        <button class="btn primary" type="submit">${t("analyze")}</button></div>
    </form>
  </section>
  <section class="card">
    <h2>${t("previous")}</h2>
    <div id="list"><p class="muted">${t("loading")}</p></div>
  </section>`;

async function fillOptions(preset, profileSel) {
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
  preset.insertAdjacentHTML("beforeend", `<option value="__custom">${t("tuningCustom")}</option>`);
}

function bindUpload(preset, profileSel) {
  preset.addEventListener("change", () => { qs("#custom-tuning").hidden = preset.value !== "__custom"; });
  qs("#upload").addEventListener("submit", async (ev) => {
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
    qs("#upload-msg").textContent = t("uploading");
    try {
      const { id } = await api("/api/analyses", { method: "POST", body: data });
      location.hash = `#/a/${id}`;
    } catch (e) {
      qs("#upload-msg").innerHTML = `<span class="error">${esc(e.message)}</span>`;
      btn.disabled = false;
    }
  });
}

function renderList(items, rerender) {
  const list = qs("#list");
  if (!list) return;
  if (!items.length) { list.innerHTML = `<p class="muted">${t("noAnalyses")}</p>`; return; }
  const statusText = (i) => ({
    done: t("statusDone", { ok: i.notes_ok, checked: i.notes_checked }),
    error: t("statusError"),
    running: `${stageText(i.stage)} (${Math.round((i.progress || 0) * 100)} %)`,
    queued: t("statusQueued"),
  }[i.status] || i.status);
  const busy = (i) => i.status === "running" || i.status === "queued";
  list.innerHTML = `<table class="list"><thead><tr><th>${t("date")}</th><th>${t("scoreAudio")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>
    ${items.map((i) => `<tr>
      <td class="mono">${new Date(i.created * 1000).toLocaleString(dateLocale(), { dateStyle: "short", timeStyle: "short" })}</td>
      <td><a href="#/a/${i.id}">${esc(i.title || i.score_name)}</a><br><span class="muted">${esc(i.audio_name)}</span></td>
      <td><span class="status"><span class="dot ${i.status}"></span>${esc(statusText(i))}</span></td>
      <td style="text-align:right"><button class="btn small" data-del="${i.id}" ${busy(i) ? "disabled" : ""}>${t("delete")}</button></td>
    </tr>`).join("")}</tbody></table>`;
  qsa("[data-del]", list).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(t("confirmDelete"))) return;
    await api(`/api/analyses/${b.dataset.del}`, { method: "DELETE" });
    rerender();
  }));
}

/** Startseite anzeigen; gibt eine Aufräumfunktion für den Router zurück. */
export function showHome(app) {
  app.innerHTML = template();
  const preset = qs("#tuning-preset");
  const profileSel = qs("#profile");
  fillOptions(preset, profileSel);
  bindUpload(preset, profileSel);

  let timer;
  const refresh = async () => {
    let items = [];
    try { items = await api("/api/analyses"); } catch (e) { qs("#list").innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
    renderList(items, refresh);
    if (items.some((i) => i.status === "queued" || i.status === "running")) timer = setTimeout(refresh, 1500);
  };
  refresh();
  return () => clearTimeout(timer);
}
