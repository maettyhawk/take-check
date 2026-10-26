// Kopfzeile: Untertitel, Sprachauswahl (aus den vorhandenen Sprachdateien) und Darstellung.

import { esc, qs } from "../core/dom.js";
import { getLang, languages, setLang, t } from "../core/i18n.js";
import { applyTheme, savedTheme, setTheme } from "../core/theme.js";

const BACK_ICON = `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M10 3 5 8l5 5"
  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

export function setupHeader() {
  qs(".tagline").textContent = t("tagline");
  const back = qs("#back-link");
  back.innerHTML = `${BACK_ICON}<span>${t("allAnalyses")}</span>`;
  back.title = t("toOverview");
  const theme = savedTheme();
  applyTheme(theme);
  qs("#controls").innerHTML = `
    <label title="${t("language")}"><select id="lang-select" aria-label="${t("language")}">
      ${languages().map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("")}</select></label>
    <label title="${t("theme")}"><select id="theme-select" aria-label="${t("theme")}">
      <option value="auto">◐ ${t("themeAuto")}</option><option value="light">☀ ${t("themeLight")}</option>
      <option value="dark">☾ ${t("themeDark")}</option></select></label>`;
  qs("#lang-select").value = getLang();
  qs("#theme-select").value = theme;
  qs("#lang-select").addEventListener("change", (ev) => { setLang(ev.target.value); location.reload(); });
  qs("#theme-select").addEventListener("change", (ev) => setTheme(ev.target.value));
}

/** Zurück-Link nur außerhalb der Übersicht zeigen; dort ersetzt er den Untertitel. */
export function setBackLink(visible) {
  qs("#back-link").hidden = !visible;
  qs(".tagline").hidden = visible;
}
