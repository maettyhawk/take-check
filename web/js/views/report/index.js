// Musiker-Bericht: ausgewählte Befunde als Notenausschnitte (alphaTab) mit nummerierten Marken und Feedbacktext.
// Dieselbe Seite dient als Vorschau, für den Browser-Druck und – unter #/a/<id>/report/print – für das Server-PDF.

import { api } from "../../core/api.js";
import { esc, qs } from "../../core/dom.js";
import { fmtTime, noteName } from "../../core/format.js";
import { dateLocale, getLang, renderMsg, t, where } from "../../core/i18n.js";
import { labelOf, printColorOf } from "../analysis/categories.js";
import { buildModel, computeIssues, issueDetail, shortMsg } from "../analysis/model.js";
import { renderRollExcerpt } from "./roll-excerpt.js";
import { renderScoreExcerpt } from "./score-excerpt.js";
import { flushSelection, loadSelection, saveSelection } from "./selection.js";

const ENGRAVABLE = /\.(gp|gpx|gp[345]|musicxml|xml|mxl)$/i;  // Vorlagen mit Notensatz; MIDI → Pianoroll
const MAX_BARS = 2;
const CLEFS = ["auto", "treble8", "bass", "score"];
const BASS_BELOW = 45;  // Median der Vorlagentöne unter A2 → Bassschlüssel (tiefe Riffs, 7-/8-Saiter)

/** "auto" auflösen: ein Schlüssel für den ganzen Bericht, nach der Lage der Töne in allen Ausschnitten. */
function resolveClef(result, groups, clef) {
  if (clef !== "auto") return clef;
  const pitches = result.notes.filter((n) => groups.some((g) => n.bar >= g.startBar && n.bar <= g.endBar
    && (n.occurrence ?? 1) === g.occurrence)).map((n) => n.pitch).sort((a, b) => a - b);
  if (!pitches.length) return "treble8";
  return pitches[Math.floor(pitches.length / 2)] < BASS_BELOW ? "bass" : "treble8";
}

function barOf(result, issue) {
  if (issue.bar) return issue.bar;
  return result.bars.find((b) => b.start <= issue.time && issue.time < b.end)?.number ?? 1;
}

/** Befunde (nach Zeit sortiert) zu Ausschnitten von höchstens zwei Takten desselben Durchgangs zusammenfassen. */
function groupExcerpts(result, issues) {
  const groups = [];
  for (const issue of issues) {
    const bar = barOf(result, issue);
    const occurrence = issue.occurrence ?? 1;
    const g = groups.at(-1);
    if (g && g.occurrence === occurrence && bar >= g.startBar && bar < g.startBar + MAX_BARS) {
      g.endBar = Math.max(g.endBar, bar);
      g.items.push(issue);
    } else {
      groups.push({ startBar: bar, endBar: bar, occurrence, items: [issue] });
    }
  }
  return groups;
}

/** Zeitfenster eines Ausschnitts (für die Pianoroll-Ersatzdarstellung). */
function excerptWindow(result, g) {
  const bars = result.bars.filter((b) => b.number >= g.startBar && b.number <= g.endBar && (b.occurrence ?? 1) === g.occurrence);
  if (bars.length) return { start: Math.min(...bars.map((b) => b.start)), end: Math.max(...bars.map((b) => b.end)) };
  const times = g.items.map((i) => i.time);
  return { start: Math.min(...times) - 1, end: Math.max(...times) + 1 };
}

function markOf(view, issue) {
  const note = issue.note_id != null ? view.model.notesById.get(issue.note_id) : null;
  return {
    bar: barOf(view.result, issue), beat: issue.beat ?? 1, note, time: issue.time,
    pitch: issue.played_pitch ?? note?.pitch ?? null, color: printColorOf(issue.type), label: String(issue.number),
    extra: issue.type === "extra" && issue.played_pitch != null ? `+${noteName(issue.played_pitch)}` : null,
  };
}

/** Ein Befund in der Liste; in der Vorschau mit Kommentarfeld und Entfernen-Knopf, im Druck nur mit dem Kommentar. */
function itemHtml(view, issue, selection, print) {
  const id = String(issue.id);
  const detail = [where(issue), fmtTime(issue.time), issueDetail(view, issue)].filter(Boolean).join(" · ");
  const comment = selection.comments[id] || "";
  const commentHtml = print
    ? (comment.trim() ? `<div class="item-comment-text">${esc(comment)}</div>` : "")
    : `<textarea class="item-comment" rows="1" data-comment="${esc(id)}" placeholder="${t("report.commentPlaceholder")}">${esc(comment)}</textarea>
       <div class="item-comment-text print-only">${esc(comment)}</div>`;
  const remove = print ? "" : `<button class="item-remove" data-remove="${esc(id)}" title="${t("report.remove")}" aria-label="${t("report.remove")}">✕</button>`;
  return `<li><span class="num" style="background:${printColorOf(issue.type)}">${issue.number}</span>
    <div><b>${esc(labelOf(issue.type))}</b> – ${esc(shortMsg(issue))}<div class="detail">${detail}</div>${commentHtml}</div>${remove}</li>`;
}

function excerptHtml(view, g, k, selection, print) {
  const bars = t("report.bars", { n: g.endBar > g.startBar ? 2 : 1, from: g.startBar, to: g.endBar });
  const pass = g.occurrence > 1 ? ` · ${t("report.pass", { n: g.occurrence })}` : "";
  return `<section class="excerpt">
    <h3>${bars}${pass} <span class="muted">· ${fmtTime(g.items[0].time)}</span></h3>
    <div class="excerpt-score" id="excerpt-${k}"></div>
    <ol class="excerpt-items">${g.items.map((i) => itemHtml(view, i, selection, print)).join("")}</ol></section>`;
}

function sheetHtml(view, groups, selection, print) {
  const { meta, result } = view;
  const date = new Date().toLocaleDateString(dateLocale(), { year: "numeric", month: "long", day: "numeric" });
  const feedback = selection.feedback || "";
  const feedbackBlock = print
    ? (feedback.trim() ? `<section class="sheet-feedback"><h2>${t("report.feedback")}</h2><div class="feedback-text">${esc(feedback)}</div></section>` : "")
    : `<section class="sheet-feedback"><h2>${t("report.feedback")}</h2>
        <textarea id="feedback" rows="5" placeholder="${t("report.feedbackPlaceholder")}">${esc(feedback)}</textarea>
        <div class="feedback-text print-only" id="feedback-print">${esc(feedback)}</div></section>`;
  return `<article class="sheet">
    <header class="sheet-head">
      <h1>${t("report.title")}: ${esc(result.title)}</h1>
      <div class="sheet-meta"><span>${t("report.score")}: ${esc(meta.score_name)}</span>
        <span>${t("report.take")}: ${esc(meta.audio_name)}</span><span>${t("report.date")}: ${esc(date)}</span></div>
    </header>
    ${feedbackBlock}
    <h2>${t("report.spots")}</h2>
    ${groups.length ? `<p class="sheet-legend">${t("report.legend")}</p>${groups.map((g, k) => excerptHtml(view, g, k, selection, print)).join("")}` : `<p class="muted">${t("report.none")}</p>`}
    <footer class="sheet-foot">${t("report.footer")}</footer>
  </article>`;
}

function toolsHtml(selection) {
  const source = { ai: t("report.prefillAi"), confident: t("report.prefillConfident") }[selection.source];
  return `<div class="report-tools">
    <div class="report-actions">
      <button class="btn primary" id="report-pdf">${t("report.pdf")}</button>
      <button class="btn" id="report-print" title="${t("report.printTitle")}">${t("report.print")}</button>
      <label class="report-clef">${t("report.clef")}
        <select id="report-clef">${CLEFS.map((c) => `<option value="${c}" ${selection.clef === c ? "selected" : ""}>${t(`report.clefs.${c}`)}</option>`).join("")}</select></label>
    </div>
    <p class="muted small">${t("report.selectionHint")}${source ? ` ${source}` : ""}</p>
    <p class="error" id="report-error" hidden></p>
  </div>`;
}

async function downloadPdf(id) {
  const btn = qs("#report-pdf");
  const error = qs("#report-error");
  error.hidden = true;
  btn.disabled = true;
  btn.textContent = t("report.pdfBusy");
  try {
    await flushSelection(id);
    const res = await fetch(`/api/analyses/${id}/report.pdf?lang=${getLang()}`);
    if (!res.ok) {
      let message = res.statusText;
      try { message = renderMsg((await res.json()).detail) || message; } catch { /* kein JSON */ }
      throw new Error(message);
    }
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || "report.pdf";
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = t("report.pdf");
  }
}

const autosize = (area) => { area.style.height = "auto"; area.style.height = `${area.scrollHeight + 2}px`; };

function bindTools(view, selection) {
  qs("#report-pdf").addEventListener("click", () => downloadPdf(view.id));
  qs("#report-print").addEventListener("click", () => window.print());
  const area = qs("#feedback");
  area.addEventListener("input", () => {
    qs("#feedback-print").textContent = area.value;
    autosize(area);
    selection.feedback = area.value;
    saveSelection(view, { feedback: area.value });
  });
  autosize(area);
}

/** Kommentarfelder und Entfernen-Knöpfe der Befunde; `onRemove` baut den Bericht neu (Nummern ändern sich). */
function bindItems(view, selection, onRemove) {
  for (const area of document.querySelectorAll(".item-comment")) {
    area.addEventListener("input", () => {
      area.nextElementSibling.textContent = area.value;
      autosize(area);
      if (area.value.trim()) selection.comments[area.dataset.comment] = area.value;
      else delete selection.comments[area.dataset.comment];
      saveSelection(view, { comments: { ...selection.comments } });
    });
    autosize(area);
  }
  for (const btn of document.querySelectorAll(".item-remove")) {
    btn.addEventListener("click", () => {
      selection.ids.delete(btn.dataset.remove);
      selection.source = "user";
      selection.auto = false;
      saveSelection(view, { issue_ids: [...selection.ids], source: "user", auto: false });
      onRemove();
    });
  }
}

async function renderExcerpts(view, groups, clef, isActive, instances) {
  const resolved = resolveClef(view.result, groups, clef);
  const engravable = ENGRAVABLE.test(view.meta.score_file);
  const bytes = engravable ? new Uint8Array(await (await fetch(`/api/analyses/${view.id}/score`)).arrayBuffer()) : null;
  for (const [k, g] of groups.entries()) {
    if (!isActive()) return;
    const el = qs(`#excerpt-${k}`);
    const marks = g.items.map((i) => markOf(view, i));
    try {
      if (!bytes) throw new Error("no score");
      const api = await renderScoreExcerpt(el, bytes, view.result.score_track ?? 0, g, marks, resolved);
      if (!isActive()) { api.destroy(); return; }  // Seite inzwischen verlassen
      instances.push(api);
    } catch (e) {
      if (bytes) console.warn("alphaTab:", e);
      el.innerHTML = "";
      renderRollExcerpt(el, view.result, excerptWindow(view.result, g), marks);
      el.insertAdjacentHTML("beforeend", `<p class="muted small">${bytes ? t("report.noScore") : ""} ${t("report.rollLegend")}</p>`);
    }
  }
}

/** Bericht öffnen; gibt eine Aufräumfunktion für den Router zurück. */
export function showReport(app, id, { print = false } = {}) {
  let active = true;
  const instances = [];  // alphaTab-Instanzen (hängen an Resize-Ereignissen)
  if (print) document.body.classList.add("print-mode");
  app.innerHTML = `<section class="card"><p class="muted">${t("loading")}</p></section>`;

  (async () => {
    await flushSelection(id);  // Auswahl aus der Analyse ist evtl. noch nicht gespeichert
    const [meta, result] = await Promise.all([api(`/api/analyses/${id}`), api(`/api/analyses/${id}/result`)]);
    const view = {
      id, meta, result,
      model: buildModel(result, { duration: 0 }),
      state: { timingTol: Math.round((result.options.timing_tol || 0.03) * 1000), strumEnabled: false },
      issues: [],
    };
    view.issues = computeIssues(view);
    const selection = await loadSelection(view);
    if (selection.timingTolMs && selection.timingTolMs !== view.state.timingTol) {
      view.state.timingTol = selection.timingTolMs;
      view.issues = computeIssues(view);
    }
    if (!active) return;
    let generation = 0;  // jeder Neuaufbau (Entfernen, Schlüssel) bricht laufendes Rendern ab
    const build = async () => {
      const current = ++generation;
      const isCurrent = () => active && current === generation;
      instances.splice(0).forEach((instance) => instance.destroy());
      const picked = view.issues.filter((i) => selection.ids.has(String(i.id)));
      picked.forEach((issue, k) => { issue.number = k + 1; });
      const groups = groupExcerpts(result, picked);
      const scroll = window.scrollY;
      app.innerHTML = `${print ? "" : toolsHtml(selection)}${sheetHtml(view, groups, selection, print)}`;
      window.scrollTo(0, scroll);
      if (!print) {
        bindTools(view, selection);
        bindItems(view, selection, build);
        qs("#report-clef").addEventListener("change", (ev) => {
          selection.clef = ev.target.value;
          saveSelection(view, { clef: ev.target.value });
          build();
        });
      }
      await renderExcerpts(view, groups, selection.clef, isCurrent, instances);
      if (isCurrent()) window.scrollTo(0, scroll);
    };
    await build();
  })().catch((e) => {
    document.body.dataset.reportError = e.message || String(e);
    app.innerHTML = `<section class="card"><p class="error">${esc(e.message)}</p></section>`;
  }).finally(() => {
    if (active) document.body.dataset.reportReady = "1";
  });

  return () => {
    active = false;
    instances.forEach((api) => api.destroy());
    delete document.body.dataset.reportReady;
    delete document.body.dataset.reportError;
    flushSelection(id);
  };
}
