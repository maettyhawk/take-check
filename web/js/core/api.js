// Zugriff auf das Backend; Fehlertexte kommen als übersetzbare Analysetexte und werden hier gerendert.

import { renderMsg } from "./i18n.js";

export async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let message = res.statusText;
    try { message = renderMsg((await res.json()).detail) || message; } catch { /* kein JSON */ }
    throw new Error(message);
  }
  return res.json();
}

export const postJson = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
