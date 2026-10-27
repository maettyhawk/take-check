// Kategorien-Chips mit Zählern und die Befundliste rechts neben der Pianoroll.

import { esc, qs, qsa } from "../../core/dom.js";
import { fmtTime } from "../../core/format.js";
import { t, where } from "../../core/i18n.js";
import { store } from "../../core/store.js";
import { CATEGORY_COLORS, catOf, colorOf, labelOf } from "./categories.js";
import { issueDetail, shortMsg } from "./model.js";
import { saveSelection } from "../report/selection.js";

export const confLabel = (v) =>
  `${v < 0.35 ? t("confAll") : v < 0.65 ? t("confBalanced") : t("confSure")} (${t("confFrom", { value: v.toFixed(2) })})`;

export function renderStats(view) {
  const { state, result } = view;
  const visible = view.visibleIssues();
  const counts = {};
  for (const i of view.issues.filter((i) => i.confidence >= state.minConf)) counts[catOf(i.type)] = (counts[catOf(i.type)] || 0) + 1;
  const withIssue = new Set(visible.filter((i) => i.note_id != null).map((i) => i.note_id));
  const ok = result.notes.filter((n) => !["dead", "unchecked", "omitted"].includes(n.status) && !withIssue.has(n.id)).length;
  const stats = qs("#stats");
  stats.innerHTML = `<span class="chip static"><b>${ok}/${result.summary.notes_checked}</b>&nbsp;${t("notesOk")}</span>` +
    Object.entries(CATEGORY_COLORS).map(([k, color]) => `<span class="chip ${state.cats.has(k) ? "" : "off"}" data-cat="${k}">
      <span class="sw" style="background:var(${color})"></span>${t(`cat.${k}`)} <b>${counts[k] || 0}</b></span>`).join("");
  qsa("[data-cat]", stats).forEach((el) => el.addEventListener("click", () => {
    const k = el.dataset.cat;
    if (state.cats.has(k)) state.cats.delete(k); else state.cats.add(k);
    store.set("tc.cats", [...state.cats]);
    view.refresh();
  }));
}

/** Bericht-Button: Anzahl der ausgewählten Befunde, die es in der Liste gibt. */
export function updateReportButton(view) {
  const btn = qs("#report-btn");
  if (!btn) return;
  const ids = view.report?.ids;
  const n = ids ? view.issues.filter((i) => ids.has(String(i.id))).length : 0;
  btn.textContent = t("report.button", { n });
  btn.classList.toggle("primary", n > 0);
}

/** Auswahl von Hand geändert: speichern (ab jetzt keine automatische Vorbelegung mehr) und Liste aktualisieren. */
function changePicks(view, change) {
  const { report } = view;
  change(report.ids);
  report.source = "user";
  report.auto = false;
  saveSelection(view, { issue_ids: [...report.ids], source: "user", auto: false, timing_tol_ms: view.state.timingTol });
  view.renderIssues();
}

/** Kopf der Befundliste: Sammel-Kästchen (alle sichtbaren auswählen / Auswahl leeren). */
function masterPickHtml(view, visible) {
  const ids = view.report?.ids;
  const n = ids ? visible.filter((i) => ids.has(String(i.id))).length : 0;
  const state = !ids || !ids.size ? "" : n === visible.length && n ? "checked" : "";
  return `<input type="checkbox" class="pick" id="pick-all" title="${t("report.pickAll")}" aria-label="${t("report.pickAll")}"
    ${state} ${view.report && visible.length ? "" : "disabled"} data-partial="${ids?.size && !state ? 1 : 0}">`;
}

/** Hinweis auf ausgewählte, aber gerade ausgeblendete Befunde (stehen trotzdem im Bericht). */
function hiddenPicksHtml(view, visible) {
  const ids = view.report?.ids;
  if (!ids) return "";
  const shown = new Set(visible.map((i) => String(i.id)));
  const n = view.issues.filter((i) => ids.has(String(i.id)) && !shown.has(String(i.id))).length;
  return n ? `<div class="sub">${t("report.hiddenPicks", { n })} · <a href="#" id="unpick-hidden">${t("report.unpickHidden")}</a></div>` : "";
}

export function renderIssues(view) {
  const { state } = view;
  updateReportButton(view);
  const visible = view.visibleIssues();
  const hidden = view.issues.filter((i) => i.confidence < state.minConf && state.cats.has(catOf(i.type))).length;
  qs("#issue-count").innerHTML = `<b>${t("findings", { n: visible.length })}</b>` +
    (hidden ? `<div class="sub">${t("hiddenUnsure", { n: hidden })} · <a href="#" id="show-all">${t("showAll")}</a></div>` : "") +
    hiddenPicksHtml(view, visible);
  qs("#show-all")?.addEventListener("click", (ev) => { ev.preventDefault(); view.setConfidence(0); });
  qs("#pick-all-slot").innerHTML = masterPickHtml(view, visible);
  const all = qs("#pick-all");
  all.indeterminate = all.dataset.partial === "1";
  all.addEventListener("change", () => changePicks(view, (ids) => {
    if (all.checked) visible.forEach((i) => ids.add(String(i.id)));
    else ids.clear();
  }));
  qs("#unpick-hidden")?.addEventListener("click", (ev) => {
    ev.preventDefault();
    const shown = new Set(visible.map((i) => String(i.id)));
    changePicks(view, (ids) => { for (const id of [...ids]) if (!shown.has(id)) ids.delete(id); });
  });
  const list = qs("#issues");
  if (!visible.length) { list.innerHTML = `<div class="empty">${t("noFindings")}</div>`; return; }
  list.innerHTML = visible.map((i) => {
    const detail = issueDetail(view, i);
    const picked = view.report?.ids.has(String(i.id));
    return `<div class="issue ${state.selected === i.id ? "sel" : ""}" data-id="${i.id}">
      <span class="bar" style="background:var(${colorOf(i.type)})"></span>
      <div><div class="where"><span>${where(i)} · ${fmtTime(i.time)}</span>
        <span title="${t("confTitle", { value: i.confidence.toFixed(2) })}"><span class="conf"><b style="width:${i.confidence * 100}%"></b></span></span></div>
        <div class="msg"><b>${esc(labelOf(i.type))}</b> – ${esc(shortMsg(i))}</div>
        ${detail ? `<div class="detail">${detail}</div>` : ""}</div>
      <input type="checkbox" class="pick" data-pick="${esc(i.id)}" title="${t("report.pick")}" aria-label="${t("report.pick")}"
        ${picked ? "checked" : ""} ${view.report ? "" : "disabled"}></div>`;
  }).join("");
  qsa(".issue", list).forEach((el) => el.addEventListener("click", (ev) => {
    if (!ev.target.closest(".pick")) view.select(el.dataset.id, true);
  }));
  qsa(".pick", list).forEach((box) => box.addEventListener("change", () => changePicks(view, (ids) => {
    if (box.checked) ids.add(box.dataset.pick); else ids.delete(box.dataset.pick);
  })));
}
