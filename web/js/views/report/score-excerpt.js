// Notenausschnitt (Noten + Tabulatur) mit alphaTab direkt aus der Vorlage: Saiten, Bünde und Notation genau wie
// im Guitar-Pro-/MusicXML-File. Betroffene Noten werden eingefärbt; Nummern (und bei zusätzlichen Tönen der gespielte
// Ton) liegen als HTML-Bubbles über der Grafik, damit sie nicht mit Texten aus der Vorlage kollidieren.

const VENDOR = new URL("../../../vendor/alphatab/", import.meta.url);
const TICKS_PER_QUARTER = 960;
const BEAT_TOLERANCE = 40;  // Ticks; Zählzeiten der Analyse sind auf 3 Stellen gerundet

let alphaTab = null;
async function loadAlphaTab() {
  alphaTab ??= await import(new URL("alphaTab.core.min.mjs", VENDOR).href);
  return alphaTab;
}

function settingsFor(at, excerpt) {
  const s = new at.Settings();
  s.core.fontDirectory = new URL("font/", VENDOR).href;
  s.core.useWorkers = false;
  s.core.enableLazyLoading = false;
  s.core.engine = "svg";
  s.player.playerMode = at.PlayerMode.Disabled;
  s.display.layoutMode = at.LayoutMode.Horizontal;
  s.display.staveProfile = at.StaveProfile.ScoreTab;
  s.display.startBar = excerpt.startBar;
  s.display.barCount = excerpt.endBar - excerpt.startBar + 1;
  s.display.scale = 0.8;
  return s;
}

/** Schläge (alle Stimmen) eines Takts nahe der Zählzeit; Zählzeit der Analyse in Einheiten des Taktnenners. */
function beatsNear(staff, masterBar, beat) {
  const bar = staff.bars[masterBar.index];
  if (!bar) return [];
  const ticks = Math.round((beat - 1) * TICKS_PER_QUARTER * 4 / masterBar.timeSignatureDenominator);
  const all = bar.voices.flatMap((v) => v.beats).filter((b) => !b.isEmpty || b.notes.length);
  if (!all.length) return [];
  const exact = all.filter((b) => Math.abs(b.displayStart - ticks) <= BEAT_TOLERANCE);
  if (exact.length) return exact;
  // z. B. zusätzliche Töne zwischen zwei Schlägen: nächstgelegener Schlag
  const nearest = Math.min(...all.map((b) => Math.abs(b.displayStart - ticks)));
  return all.filter((b) => Math.abs(b.displayStart - ticks) === nearest);
}

/** Die Note der Vorlage in alphaTabs Modell: über Saite/Bund, sonst über die Tonhöhe. */
function findNote(beats, note, stringCount) {
  const notes = beats.flatMap((b) => b.notes);
  if (note.string) {
    // Analyse zählt Saiten von der höchsten (1) an, alphaTab von der tiefsten
    const atString = stringCount + 1 - note.string;
    const byTab = notes.find((n) => n.string === atString && n.fret === note.fret);
    if (byTab) return byTab;
  }
  const pitch = note.fretted_pitch ?? note.pitch;
  return notes.find((n) => n.realValue === pitch) ?? null;
}

function colorNote(at, note, color) {
  const c = at.model.Color.fromJson(color);
  note.style ??= new at.model.NoteStyle();
  for (const part of ["StandardNotationNoteHead", "GuitarTabFretNumber"]) note.style.colors.set(at.model.NoteSubElement[part], c);
}

/**
 * Marken zuordnen: {bar, beat, note (Vorlagennote oder null), color, label, extra (z. B. "+D3")}. Betroffene Noten
 * werden eingefärbt; Ergebnis: Schlag → Marken, für die Bubbles nach dem Rendern.
 */
function applyMarks(at, score, track, marks) {
  const staff = track.staves[0];
  const stringCount = staff.tuning?.length || 6;
  const byBeat = new Map();
  for (const mark of marks) {
    const masterBar = score.masterBars[mark.bar - 1];
    if (!masterBar) continue;
    const beats = beatsNear(staff, masterBar, mark.beat);
    if (!beats.length) continue;
    const found = mark.note ? findNote(beats, mark.note, stringCount) : null;
    if (found) colorNote(at, found, mark.color);
    const target = found?.beat ?? beats.find((b) => b.notes.length) ?? beats[0];
    if (!byBeat.has(target)) byBeat.set(target, []);
    byBeat.get(target).push(mark);
  }
  return byBeat;
}

function bubble(className, text, style) {
  const el = document.createElement("span");
  el.className = className;
  el.textContent = text;
  Object.assign(el.style, style);
  return el;
}

/** Nummern über dem System, gespielte Töne zusätzlicher Noten unter der Tabulatur – je Schlag nebeneinander. */
function drawBubbles(el, lookup, byBeat) {
  const surface = el.querySelector(".at-surface");
  if (!surface || !lookup) return;
  surface.style.position = "relative";
  for (const [beat, marks] of byBeat) {
    const bounds = lookup.findBeat(beat);
    if (!bounds) continue;
    const system = bounds.barBounds.masterBarBounds.realBounds;
    const x = bounds.onNotesX;
    const nums = document.createElement("span");
    nums.className = "score-marks";
    Object.assign(nums.style, { left: `${x}px`, top: `${system.y}px` });
    for (const m of marks) nums.append(bubble("score-mark", m.label, { background: m.color }));
    surface.append(nums);
    const extras = marks.filter((m) => m.extra);
    if (!extras.length) continue;
    const below = document.createElement("span");
    below.className = "score-extras";
    Object.assign(below.style, { left: `${x}px`, top: `${system.y + system.h}px` });
    for (const m of extras) below.append(bubble("score-extra", m.extra, { borderColor: m.color, color: m.color }));
    surface.append(below);
  }
}

/**
 * Haltebögen, die aus einem Takt vor dem Ausschnitt kommen, lösen: alphaTab stürzt beim Layout ab, wenn der
 * Ursprung nicht mitgerendert wird. Die Note erscheint dann als normaler Anschlag am Ausschnittsbeginn.
 */
function cutIncomingTies(track, startBar) {
  for (const staff of track.staves) {
    for (const voice of staff.bars[startBar - 1]?.voices ?? []) {
      for (const note of voice.beats.flatMap((b) => b.notes)) {
        if (note.tieOrigin && note.tieOrigin.beat.voice.bar.index < startBar - 1) {
          note.tieOrigin = null;
          note.isTieDestination = false;
        }
      }
    }
  }
}

// Werte aus alphaTabs Enums (die Namen sind im minifizierten Bundle verkürzt, die Zahlen sind dokumentiert)
const CLEF_G2 = 4;
const CLEF_F4 = 3;
const OTTAVA_REGULAR = 2;
const OTTAVA_8VB = 3;

/**
 * Notenschlüssel setzen. Gitarrenvorlagen stehen meist im Violinschlüssel mit Transposition um eine Oktave.
 * treble8: Violinschlüssel mit 8 darunter (gleiche Notenbilder, korrekt bezeichnet); bass: Bassschlüssel in
 * klingender Höhe; score: wie in der Vorlage.
 */
function applyClef(track, clef) {
  if (clef !== "treble8" && clef !== "bass") return;
  for (const staff of track.staves) {
    if (staff.isPercussion) continue;
    staff.displayTranspositionPitch = 0;  // die Oktave steckt im Schlüssel bzw. entfällt im Bassschlüssel
    for (const bar of staff.bars) {
      bar.clef = clef === "bass" ? CLEF_F4 : CLEF_G2;
      bar.clefOttava = clef === "bass" ? OTTAVA_REGULAR : OTTAVA_8VB;
    }
  }
}

/** alphaTab schreibt fest „rendered by alphaTab“ unter jede Grafik – im Bericht steht der Hinweis einmal unten. */
function hideWatermark(el) {
  for (const part of el.querySelectorAll(".at-surface > div")) {
    if (part.textContent.includes("rendered by alphaTab")) part.style.display = "none";
  }
}

function fitWidth(el) {
  const surface = el.querySelector(".at-surface");
  const width = surface?.scrollWidth || 0;
  if (width > el.clientWidth) surface.style.zoom = String(el.clientWidth / width);
}

/**
 * Ausschnitt in `el` rendern. `bytes`: Vorlage (GP/MusicXML) als Uint8Array, `excerpt`: {startBar, endBar} (1-basiert),
 * `clef`: siehe applyClef,
 * `marks`: siehe applyMarks. Gibt die alphaTab-Instanz zurück (zum Aufräumen: destroy()); wirft, wenn die Vorlage
 * nicht gelesen oder gerendert werden kann.
 */
export async function renderScoreExcerpt(el, bytes, trackIndex, excerpt, marks, clef = "score") {
  const at = await loadAlphaTab();
  const settings = settingsFor(at, excerpt);
  const score = at.importer.ScoreLoader.loadScoreFromBytes(bytes, settings);
  const track = score.tracks[trackIndex] ?? score.tracks[0];
  cutIncomingTies(track, excerpt.startBar);
  applyClef(track, clef);
  const byBeat = applyMarks(at, score, track, marks);
  const api = new at.AlphaTabApi(el, settings);
  try {
    await new Promise((resolve, reject) => {
      api.renderFinished.on(resolve);
      api.error.on(reject);
      api.renderScore(score, [track.index]);
    });
  } catch (e) {
    api.destroy();
    throw e;
  }
  await new Promise(requestAnimationFrame);
  hideWatermark(el);
  drawBubbles(el, api.boundsLookup, byBeat);
  fitWidth(el);
  return api;
}
