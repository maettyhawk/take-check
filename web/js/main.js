// Take Check – Einstieg: Übersetzungen laden, Kopfzeile aufbauen, zwischen Startseite und Analyse umschalten.

import { qs } from "./core/dom.js";
import { initI18n } from "./core/i18n.js";
import { setBackLink, setupHeader } from "./ui/header.js";
import { showAnalysis } from "./views/analysis/index.js";
import { showHome } from "./views/home.js";

const app = qs("#app");
let cleanup = () => {};

function route() {
  cleanup();
  qs("#tooltip").hidden = true;
  const match = location.hash.match(/^#\/a\/([\w-]+)/);
  setBackLink(Boolean(match));
  cleanup = (match ? showAnalysis(app, match[1]) : showHome(app)) || (() => {});
}

await initI18n();
setupHeader();
window.addEventListener("hashchange", route);
route();
