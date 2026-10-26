// Darstellung: Auto (System), Hell oder Dunkel.

import { store } from "./store.js";

export function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

export function setTheme(theme) {
  store.set("tc.theme", theme);
  applyTheme(theme);
  window.dispatchEvent(new Event("themechange"));
}

export const savedTheme = () => store.get("tc.theme", "auto");
