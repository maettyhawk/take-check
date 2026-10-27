// Analyseansicht: Status abfragen, bis das Ergebnis da ist, dann alle Teile zusammensetzen.

import { api, postJson } from "../../core/api.js";
import { esc, qs } from "../../core/dom.js";
import { stageText, t } from "../../core/i18n.js";
import { store } from "../../core/store.js";
import { mountAiPanel } from "./ai-panel.js";
import { CATEGORY_COLORS } from "./categories.js";
import { bindControls } from "./controls.js";
import { confLabel, renderIssues, renderStats } from "./issue-list.js";
import { buildModel, computeIssues, isVisible } from "./model.js";
import { selectIssue } from "./navigation.js";
import { createPianoroll } from "./pianoroll.js";
import { analysisTemplate } from "./template.js";
import { flushSelection, loadSelection, saveSelection } from "../report/selection.js";
import { attachTooltip } from "./tooltip.js";

function initialState(result) {
  const categories = Object.keys(CATEGORY_COLORS);
  const state = {
    pps: store.get("tc.pps", 120),
    timingTol: Math.round((result.options.timing_tol || 0.03) * 1000),
    minConf: store.get("tc.minConf", 0.5),
    cats: new Set(store.get("tc.cats", categories)),
    selected: null,
    preroll: store.get("tc.preroll", "bar1"),
    // Anschlagsrichtung nur, wenn das Profil sie freigibt (Erkennung nicht für alle Akkorde zuverlässig)
    strumEnabled: Boolean(result.display?.strum_direction),
    showStrum: store.get("tc.showStrum", true),
    offsetDraft: result.offset,
  };
  // neu hinzugekommene Kategorien sind auch bei gespeicherten Filtern zunächst sichtbar
  const known = new Set(store.get("tc.knownCats", categories));
  for (const k of categories) if (!known.has(k)) state.cats.add(k);
  store.set("tc.knownCats", categories);
  return state;
}

/** Fertiges Ergebnis darstellen; gibt eine Aufräumfunktion zurück. */
function renderAnalysis(app, { id, meta, result, peaks, reload }) {
  const view = {
    id, meta, result, peaks, reload,
    model: buildModel(result, peaks),
    state: initialState(result),
    issues: [],
    report: null,
    visibleIssues() { return this.issues.filter((i) => isVisible(this.state, i)); },
    refresh() { this.issues = computeIssues(this); renderStats(this); renderIssues(this); this.draw(); },
    renderIssues() { renderIssues(this); },
    draw() { this.pianoroll.draw(); },
    select(issueId, play) { selectIssue(this, issueId, play); },
    setConfidence(value) {
      this.state.minConf = value;
      store.set("tc.minConf", value);
      qs("#conf").value = value;
      qs("#conf-v").textContent = confLabel(value);
      this.refresh();
    },
  };
  app.innerHTML = analysisTemplate(view);
  view.el = {
    audio: qs("#audio"), scroll: qs("#scroll"), spacer: qs("#spacer"),
    roll: qs("#roll"), wave: qs("#wave"), tooltip: qs("#tooltip"),
  };
  view.pianoroll = createPianoroll(view);
  attachTooltip(view);
  const disposers = [bindControls(view), mountAiPanel(view)];
  if (meta.outdated) showOutdatedNotice(view);
  view.pianoroll.size();
  view.refresh();
  let disposed = false;
  // Berichtsauswahl nachladen (Kästchen in der Befundliste)
  loadSelection(view, view.visibleIssues()).then((selection) => {
    if (disposed) return;
    view.report = selection;
    // Vorbelegung gleich speichern, damit Vorschau und PDF genau diese Auswahl zeigen
    if (selection.auto) {
      saveSelection(view, { issue_ids: [...selection.ids], source: selection.source, auto: true, timing_tol_ms: view.state.timingTol });
    }
    view.renderIssues();
  }).catch(() => {});
  return () => { disposed = true; disposers.forEach((dispose) => dispose()); flushSelection(id); };
}

function showOutdatedNotice(view) {
  qs(".summary-head").insertAdjacentHTML("afterend", `<div class="notice">${t("outdated")}
    <button class="btn small primary" id="refresh-analysis">${t("recompute")}</button></div>`);
  qs("#refresh-analysis").addEventListener("click", async () => {
    await postJson(`/api/analyses/${view.id}/rerun`, {});
    view.reload();
  });
}

/** Analyseansicht öffnen; gibt eine Aufräumfunktion für den Router zurück. */
export function showAnalysis(app, id) {
  let timer;
  let disposeView = () => {};
  let active = true;
  app.innerHTML = `<section class="card"><p class="muted">${t("loading")}</p></section>`;

  const reload = () => { disposeView(); disposeView = () => {}; poll(); };

  async function poll() {
    let meta;
    try { meta = await api(`/api/analyses/${id}`); } catch (e) {
      app.innerHTML = `<section class="card"><p class="error">${esc(e.message)}</p><a href="#/">${t("toOverview")}</a></section>`;
      return;
    }
    if (!active) return;
    if (meta.status === "done") {
      const [result, peaks] = await Promise.all([api(`/api/analyses/${id}/result`), api(`/api/analyses/${id}/peaks`)]);
      if (active) disposeView = renderAnalysis(app, { id, meta, result, peaks, reload });
    } else if (meta.status === "error") {
      app.innerHTML = `<section class="card"><h2>${t("failed")}</h2><p class="error">${esc(meta.error)}</p>
        <p class="muted">${esc(meta.score_name)} · ${esc(meta.audio_name)}</p><a href="#/">${t("toOverview")}</a></section>`;
    } else {
      app.innerHTML = `<section class="card"><h2>${esc(meta.score_name)} · ${esc(meta.audio_name)}</h2>
        <div class="progress"><div style="width:${Math.round((meta.progress || 0) * 100)}%"></div></div>
        <p class="muted">${esc(stageText(meta.stage))} …</p></section>`;
      timer = setTimeout(poll, 800);
    }
  }
  poll();
  return () => { active = false; clearTimeout(timer); disposeView(); };
}
