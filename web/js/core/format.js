// Formatierung von Tonhöhen, Zeiten und Zählzeiten.

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

export const noteName = (midi) => `${NOTE_NAMES[midi % 12]}${Math.floor(midi / 12) - 1}`;
export const fmtTime = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
export const fmtBeat = (b) => (+b).toFixed(2).replace(/\.?0+$/, "");
