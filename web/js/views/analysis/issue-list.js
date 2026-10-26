// Kategorien-Chips mit Zählern und die Befundliste rechts neben der Pianoroll.

import { esc, qs, qsa } from "../../core/dom.js";
import { fmtTime } from "../../core/format.js";
import { t, where } from "../../core/i18n.js";
import { store } from "../../core/store.js";
import { CATEGORY_COLORS, catOf, colorOf, labelOf } from "./categories.js";
import { issueDetail, shortMsg } from "./model.js";

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

export function renderIssues(view) {
  const { state } = view;
  const visible = view.visibleIssues();
  const hidden = view.issues.filter((i) => i.confidence < state.minConf && state.cats.has(catOf(i.type))).length;
  qs("#issue-count").innerHTML = `<b>${t("findings", { n: visible.length })}</b>` +
    (hidden ? `<div class="sub">${t("hiddenUnsure", { n: hidden })} · <a href="#" id="show-all">${t("showAll")}</a></div>` : "");
  qs("#show-all")?.addEventListener("click", (ev) => { ev.preventDefault(); view.setConfidence(0); });
  const list = qs("#issues");
  if (!visible.length) { list.innerHTML = `<div class="empty">${t("noFindings")}</div>`; return; }
  list.innerHTML = visible.map((i) => {
    const detail = issueDetail(view, i);
    return `<div class="issue ${state.selected === i.id ? "sel" : ""}" data-id="${i.id}">
      <span class="bar" style="background:var(${colorOf(i.type)})"></span>
      <div><div class="where"><span>${where(i)} · ${fmtTime(i.time)}</span>
        <span title="${t("confTitle", { value: i.confidence.toFixed(2) })}"><span class="conf"><b style="width:${i.confidence * 100}%"></b></span></span></div>
        <div class="msg"><b>${esc(labelOf(i.type))}</b> – ${esc(shortMsg(i))}</div>
        ${detail ? `<div class="detail">${detail}</div>` : ""}</div></div>`;
  }).join("");
  qsa(".issue", list).forEach((el) => el.addEventListener("click", () => view.select(el.dataset.id, true)));
}
