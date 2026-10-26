// Übersetzungen: lädt die Sprachdateien des Servers (src/take_check/locales/*.json) und rendert Texte.
// Oberflächentexte stehen unter "ui", Analysetexte unter "msg". Fehlende Einträge fallen auf Englisch zurück.

import { fmtBeat } from "./format.js";
import { store } from "./store.js";

const REFERENCE = "en";
let current = null;     // Sprachdatei der gewählten Sprache
let fallback = null;    // englische Referenz
let lang = REFERENCE;
let available = [];
let plural = new Intl.PluralRules(REFERENCE);

async function fetchJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function detect(codes) {
  const saved = store.get("tc.lang", null);
  if (codes.includes(saved)) return saved;
  // erste bevorzugte Browser-Sprache, die es als Datei gibt; sonst Englisch
  const prefs = navigator.languages?.length ? navigator.languages : [navigator.language || REFERENCE];
  for (const pref of prefs.map((l) => l.toLowerCase())) {
    if (codes.includes(pref)) return pref;
    const base = pref.split("-")[0];
    if (codes.includes(base)) return base;
  }
  return REFERENCE;
}

export async function initI18n() {
  available = await fetchJson("/api/locales");
  lang = detect(available.map((l) => l.code));
  [current, fallback] = await Promise.all([
    fetchJson(`/api/locales/${lang}`),
    lang === REFERENCE ? null : fetchJson(`/api/locales/${REFERENCE}`),
  ]);
  fallback = fallback || current;
  plural = new Intl.PluralRules(lang);
  document.documentElement.lang = lang;
}

export const getLang = () => lang;
export const languages = () => available;
export const dateLocale = () => current?.meta?.date_locale || lang;
export function setLang(code) { store.set("tc.lang", code); }

function lookup(section, key) {
  for (const data of [current, fallback]) {
    let node = data?.[section];
    for (const part of key.split(".")) node = node && typeof node === "object" ? node[part] : undefined;
    if (node !== undefined) return node;
  }
  return undefined;
}

function format(template, params) {
  if (template && typeof template === "object") {
    template = template[plural.select(Number(params.n))] ?? template.other ?? Object.values(template)[0];
  }
  return String(template).replace(/\{(\w+)\}/g, (all, name) => (name in params ? renderMsg(params[name]) : all));
}

/** Oberflächentext; `fallbackText` statt des Schlüssels, wenn es keinen Eintrag gibt. */
export function t(key, params = {}, fallbackText = key) {
  const template = lookup("ui", key);
  return template === undefined ? fallbackText : format(template, params);
}

/**
 * Analysetext rendern: {k, p} aus der Analyse, Listen davon (verkettet), alte {de, en}-Texte, einfache Strings.
 * `skip`: Textschlüssel, die weggelassen werden (z. B. Zusätze, die die Oberfläche anders darstellt).
 */
export function renderMsg(value, { skip = [] } = {}) {
  if (value == null) return "";
  if (Array.isArray(value)) return value.map((part) => renderMsg(part, { skip })).join("");
  if (typeof value === "object") {
    if ("k" in value) {
      if (skip.includes(value.k)) return "";
      const template = lookup("msg", value.k);
      return template === undefined ? value.k : format(template, value.p || {});
    }
    return value[lang] ?? value[REFERENCE] ?? value.de ?? "";  // Ergebnisse vor Version 3
  }
  return String(value);
}

/** Taktangabe eines Befunds oder einer Note. */
export const where = (item) => t("where", {
  bar: item.bar, beat: fmtBeat(item.beat), pass: item.occurrence > 1 ? t("wherePass", { n: item.occurrence }) : "",
});

/** Saite/Bund einer Note (leer ohne Tabulatur). */
export const tab = (note) => (note.string ? t("tab", { string: note.string, fret: note.fret }) : "");

/** Fortschrittsstufe der Analyse (alte Ergebnisse speichern noch deutsche Namen). */
export const stageText = (stage) => (stage ? t(`stages.${stage}`, {}, stage) : t("statusQueued"));
