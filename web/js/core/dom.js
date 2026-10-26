// Kleine DOM-Helfer (reines Browser-JavaScript, keine Bibliothek).

/** Erstes Element zum CSS-Selektor. */
export const qs = (selector, root = document) => root.querySelector(selector);
/** Alle Elemente zum CSS-Selektor als Array. */
export const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

/** Text für die Ausgabe in HTML maskieren. */
export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/** Wert einer CSS-Variablen (Farben passen sich so dem Theme an). */
export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
