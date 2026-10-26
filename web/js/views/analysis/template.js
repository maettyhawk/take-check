// HTML-Gerüst der Analyseansicht.

import { esc } from "../../core/dom.js";
import { noteName } from "../../core/format.js";
import { renderMsg, t } from "../../core/i18n.js";

export function analysisTemplate(view) {
  const { id, meta, result, state } = view;
  const warnings = result.warnings || [];
  const hints = result.hints || [];
  const tuningText = result.tuning ? result.tuning.map(noteName).join(" ") : t("fromNotation");
  const cents = result.tuning_cents != null
    ? `<span class="muted">(${result.tuning_cents >= 0 ? "+" : ""}${result.tuning_cents} ${t("cents")})</span>` : "";
  return `
    <section class="card">
      <div class="summary-head">
        <h1>${esc(result.title)}</h1>
        <span class="muted">${esc(meta.score_name)} · ${esc(meta.audio_name)}${result.profile ? ` · ${t("profile")}: ${esc(result.profile.name)}` : ""}</span>
        <a href="#/">${t("allAnalyses")}</a>
      </div>
      <div class="stats" id="stats"></div>
      ${warnings.length ? `<ul class="warnings">${warnings.map((w) => `<li>${esc(renderMsg(w))}</li>`).join("")}</ul>` : ""}
      ${hints.length ? `<ul class="hints">${hints.map((h) => `<li>${esc(renderMsg(h))}</li>`).join("")}</ul>` : ""}
      <div class="controls-row">
        <div class="group">${t("offset")} <span class="mono" id="offset">${result.offset.toFixed(3)} s</span>
          <button class="btn small" data-off="-0.01">−10 ms</button><button class="btn small" data-off="0.01">+10 ms</button>
          <button class="btn small" id="apply-offset" disabled>${t("recompute")}</button>
          <button class="btn small" id="auto-offset" title="${t("autoTitle")}">${t("auto")}</button></div>
        <div class="group">${t("tuning")} <span class="mono">${esc(tuningText)}</span>${cents}</div>
      </div>
    </section>
    <section class="card ai-panel" id="ai-panel"></section>
    <div class="toolbar">
      <div class="group"><button class="btn play" id="play" title="${t("play")}">▶</button>
        <span class="mono" id="clock">0:00.0</span></div>
      <label class="group">${t("zoom")} <input type="range" id="zoom" min="30" max="600" step="10" value="${state.pps}"></label>
      <label class="group">${t("timingTol")} <input type="range" id="tol" min="10" max="120" step="5" value="${state.timingTol}"><span class="mono" id="tol-v">${state.timingTol} ms</span></label>
      ${state.strumEnabled ? `<label class="group" title="${t("strumTitle")}"><input type="checkbox" id="strum" ${state.showStrum ? "checked" : ""}> ${t("strum")}</label>` : ""}
      <label class="group" title="${t("prerollTitle")}">${t("preroll")}
        <select id="preroll">
          <option value="0">0 s</option><option value="0.5">0.5 s</option><option value="1">1 s</option>
          <option value="bar1">${t("bar1")}</option><option value="bar2">${t("bar2")}</option>
        </select></label>
      <label class="group" title="${t("confidenceTitle")}">${t("confidence")}
        <input type="range" id="conf" min="0" max="0.95" step="0.05" value="${state.minConf}"><span id="conf-v"></span></label>
    </div>
    <div class="workspace">
      <div class="viewer">
        <div class="scroll" id="scroll"><div class="spacer" id="spacer"></div>
          <canvas class="sticky" id="roll"></canvas><canvas class="sticky" id="wave"></canvas></div>
        <div class="legend">
          <span><i></i>${t("legScore")}</span>
          <span><i style="background:var(--det);border-color:var(--det);height:4px"></i>${t("legDetected")}</span>
          <span><i style="border-style:dashed;border-color:var(--c-notes)"></i>${t("legMissing")}</span>
          <span><i style="border-style:dashed;border-color:var(--muted)"></i>${t("legOmitted")}</span>
          <span><i style="border-style:dotted"></i>${t("legUnchecked")}</span>
          <span><i style="border-bottom:3px solid var(--c-pm)"></i>Palm Mute</span>
          <span><i style="background:var(--c-stops);opacity:.35;border-color:var(--c-stops)"></i>${t("legRest")}</span>
          ${state.strumEnabled ? `<span><b style="color:var(--strum-down)">↓</b> ${t("legDown")} · <b style="color:var(--strum-up)">↑</b> ${t("legUp")} · <b class="muted">·</b> ${t("legUnclear")}</span>` : ""}
          <span>◇ ${t("legHarm")}</span><span>× Dead Note</span><span>⌒ ${t("legLegato")}</span>
          <span><i style="border:0;border-top:2px dashed var(--c-bend);border-radius:0;height:2px"></i> / <i style="border:0;border-top:2px solid var(--c-bend);border-radius:0;height:2px"></i>${t("legBend")}</span>
          <span class="muted">${t("keys")}</span>
        </div>
      </div>
      <aside class="issues">
        <div class="issues-head"><div id="issue-count"></div><button class="btn small" id="copy" title="${t("copyTitle")}">${t("copy")}</button></div>
        <div class="issues-list" id="issues"></div>
      </aside>
    </div>
    <audio id="audio" preload="auto" src="/api/analyses/${id}/audio"></audio>`;
}
