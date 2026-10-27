// Take Check – Einstieg: Übersetzungen laden, Kopfzeile aufbauen, zwischen Startseite, Analyse und Bericht umschalten.

import { qs } from "./core/dom.js";
import { initI18n, t } from "./core/i18n.js";
import { setBackLink, setupHeader } from "./ui/header.js";
import { showAnalysis } from "./views/analysis/index.js";
import { showHome } from "./views/home.js";
import { showReport } from "./views/report/index.js";

const app = qs("#app");
let cleanup = () => {};

function route() {
  cleanup();
  qs("#tooltip").hidden = true;
  document.body.classList.remove("print-mode");
  const report = location.hash.match(/^#\/a\/([\w-]+)\/report(\/print)?/);
  const analysis = location.hash.match(/^#\/a\/([\w-]+)/);
  let view;
  if (report) {
    setBackLink({ href: `#/a/${report[1]}`, label: t("report.back") });
    view = showReport(app, report[1], { print: Boolean(report[2]) });
  } else if (analysis) {
    setBackLink({ href: "#/", label: t("allAnalyses"), title: t("toOverview") });
    view = showAnalysis(app, analysis[1]);
  } else {
    setBackLink(null);
    view = showHome(app);
  }
  cleanup = view || (() => {});
}

await initI18n();
setupHeader();
window.addEventListener("hashchange", route);
route();
