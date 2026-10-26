// Einstellungen pro Browser (localStorage); fällt still aus, wenn der Speicher blockiert ist.

export const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* privat/blockiert */ }
  },
};
