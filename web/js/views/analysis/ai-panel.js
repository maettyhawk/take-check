// KI-Check: Einschätzung durch Claude anfordern und anzeigen; Verweise springen zur Stelle.

import { api, postJson } from "../../core/api.js";
import { esc, qs, qsa } from "../../core/dom.js";
import { getLang, renderMsg, t } from "../../core/i18n.js";
import { store } from "../../core/store.js";
import { jumpToServerIssue } from "./navigation.js";

const refs = (ids) => ids.slice(0, 8).map((i) => `<a href="#" data-issue="${i}">#${i}</a>`).join(" ");

function reviewHtml(ai) {
  const r = ai.result.review;
  let html = ai.stale ? `<p class="notice">${t("ai.stale")}</p>` : "";
  html += `<h3>${t("ai.summary")}</h3><p>${esc(r.summary)}</p>`;
  if (r.listen_first.length) {
    html += `<h3>${t("ai.listen")}</h3><ol class="ai-list">${r.listen_first.map((it, k) => `
      <li class="ai-item" data-k="${k}"><span class="prio ${it.priority}">${t(`ai.prio.${it.priority}`, {}, it.priority)}</span>
        <b>${esc(it.bars)}</b> – ${esc(it.title)}<div class="muted">${esc(it.reason)}</div>
        ${it.issue_ids.length ? `<div class="refs">${refs(it.issue_ids)}
          <span class="muted">(${t("ai.findingsRef", { n: it.issue_ids.length })})</span></div>` : ""}</li>`).join("")}</ol>`;
  }
  if (r.likely_artifacts.length) {
    html += `<h3>${t("ai.artifacts")}</h3><ul class="ai-list">${r.likely_artifacts.map((it) => `<li>${esc(it.reason)}
      ${it.issue_ids.length ? `<div class="refs">${refs(it.issue_ids)}</div>` : ""}</li>`).join("")}</ul>`;
  }
  if (r.patterns.length) html += `<h3>${t("ai.patterns")}</h3><ul class="ai-list">${r.patterns.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>`;
  html += `<h3>${t("ai.feedback")} <button class="btn small" id="ai-copy">${t("ai.copyFeedback")}</button></h3>
    <blockquote class="ai-feedback">${esc(r.musician_feedback).replace(/\n/g, "<br>")}</blockquote>
    <p class="muted small">${t("ai.disclaimer")} · ${esc(ai.result.model)}</p>`;
  return html;
}

function bindReview(view, panel, review) {
  qsa("[data-issue]", panel).forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); jumpToServerIssue(view, +a.dataset.issue); }));
  qsa(".ai-item", panel).forEach((li) => li.addEventListener("click", (ev) => {
    if (ev.target.closest("a")) return;
    const first = review.listen_first[+li.dataset.k].issue_ids[0];
    if (first != null) jumpToServerIssue(view, first);
  }));
  qs("#ai-copy")?.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(review.musician_feedback); qs("#ai-copy").textContent = t("copied"); }
    catch { prompt(t("copyPrompt"), review.musician_feedback); }
  });
}

/** KI-Bereich rendern (und während der Prüfung regelmäßig aktualisieren); gibt eine Aufräumfunktion zurück. */
export function mountAiPanel(view) {
  let timer;
  let disposed = false;
  const lang = getLang();

  async function render() {
    const panel = qs("#ai-panel");
    if (!panel || disposed) return;
    const [status, ai] = await Promise.all([api("/api/ai/status"), api(`/api/analyses/${view.id}/ai-check?lang=${lang}`)]);
    if (disposed) return;
    const runLabel = ai.result ? t("ai.rerun") : t("ai.run");
    const head = `<div class="ai-head"><h2>✦ ${t("ai.title")}</h2>
      ${status.configured && ai.status !== "running" ? `<button class="btn small ${ai.result ? "" : "primary"}" id="ai-run">${runLabel}</button>` : ""}</div>`;
    if (!status.configured) { panel.innerHTML = `${head}<p class="muted">${t("ai.notConfigured")}</p>`; return; }
    if (ai.status === "running") {
      panel.innerHTML = `${head}<p class="muted"><span class="spinner"></span> ${t("ai.running")}</p>`;
      timer = setTimeout(render, 2000);
      return;
    }
    const error = ai.status === "error" && ai.error ? `<p class="error">${esc(renderMsg(ai.error))}</p>` : "";
    const review = ai.result?.review;
    if (review) {
      const open = store.get("tc.aiOpen", true);
      panel.innerHTML = `${head}${error}<details class="ai-body" ${open ? "open" : ""}><summary>${t("ai.details")}</summary>${reviewHtml(ai)}</details>`;
      qs(".ai-body", panel).addEventListener("toggle", (ev) => store.set("tc.aiOpen", ev.target.open));
      bindReview(view, panel, review);
    } else {
      panel.innerHTML = `${head}<p class="muted small">${t("ai.privacy", { model: status.model })}</p>${error}`;
    }
    qs("#ai-run")?.addEventListener("click", async (ev) => {
      ev.target.disabled = true;
      try {
        await postJson(`/api/analyses/${view.id}/ai-check`, { lang });
      } catch (e) {
        panel.insertAdjacentHTML("beforeend", `<p class="error">${esc(e.message)}</p>`);
        ev.target.disabled = false;
        return;
      }
      render();
    });
  }
  render();
  return () => { disposed = true; clearTimeout(timer); };
}
