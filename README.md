# Take Check

**Instrumentaufnahme gegen Vorlage prüfen.** Take Check vergleicht eine Gitarrenaufnahme (DI-Spur) mit der
Vorlage aus Guitar Pro und markiert, wo es sich lohnt hinzuhören: falsche, fehlende oder zusätzliche Töne,
Timing gegen den eigenen Groove, Palm Mutes, Legato, Bends, Flageoletts und nicht abgedämpfte Pausen.

Die Ergebnisse sind Hinweise fürs Korrekturhören, kein Urteil – jeder Befund hat eine Sicherheit, und die
Auswertung folgt Regeln aus der Spielpraxis (z. B. dämpft der Handballen obere Saiten stärker, gleichmäßiges
Vor-/Hinterherziehen gegenüber dem Klick ist Stil und kein Fehler).

## Funktionen

- Vorlagen: Guitar Pro 7/8 (`.gp`, inkl. exakter Bend-Kurven), MusicXML (`.musicxml`/`.xml`/`.mxl`), MIDI
- Beliebige Stimmungen und 6–9 Saiten, Wiederholungen, Voltas, D.C./D.S./Coda, Tempowechsel
- Polyphone Erkennung (Basic Pitch) plus vorlagengestützte Spektralprüfung für Akkordtöne
- Web-Oberfläche mit Pianoroll, Wellenform, Befundliste, Sprung zur Stelle, Tooltips, Deutsch/Englisch, Darkmode
- Auswertungsprofile in `profiles/*.toml` (Regeln und Schwellen, erweiterbar)

## KI-Check

Optional lässt sich die Analyse von Claude (Anthropic-API) einordnen: Zuerst-anhören-Liste mit Begründung,
vermutliche Erkennungsartefakte, Muster über den Take und ein Rückmeldetext für den Musiker. Gesendet werden
nur Analysewerte (Befunde, Takte, Hinweise) – kein Audio und keine Vorlagendatei.

Der API-Schlüssel wird aus `ANTHROPIC_API_KEY` gelesen oder aus einer Datei, standardmäßig
`~/.config/take-check/anthropic_api_key` (anderer Ort per `TAKE_CHECK_API_KEY_FILE`). Den Schlüssel nie ins
Repository legen.

```bash
TAKE_CHECK_API_KEY_FILE=~/.secrets/anthropic_api_key uv run take-check serve
uv run take-check ai-check ergebnis.json            # für ein gespeichertes Ergebnis aus 'analyze -o'
```

## Bericht für den Musiker

In der Befundliste legen Kästchen fest, welche Stellen in den Bericht kommen. Vorbelegt sind die Stellen aus
„Zuerst anhören“ des KI-Checks, ohne KI-Check alle sicheren Befunde. „Bericht“ öffnet eine Vorschau mit einem
Feedbacktext (vorbelegt aus dem KI-Check) und je Stelle einem Ausschnitt aus Noten und Tabulatur. Der Ausschnitt
wird mit [alphaTab](https://alphatab.net) direkt aus der Vorlage gerendert, also mit den Saiten und Bünden aus
dem Guitar-Pro-File. Betroffene Noten sind farbig, Nummern verweisen auf die Liste darunter. Bei MIDI-Vorlagen
erscheint stattdessen ein Pianoroll-Ausschnitt.

„PDF herunterladen“ erzeugt das PDF auf dem Server mit Headless-Chromium. Das muss einmalig eingerichtet werden:

```bash
uv sync --extra pdf && uv run playwright install chromium
```

Ohne diese Einrichtung funktioniert „Drucken“ trotzdem: Druckdialog des Browsers, dort „Als PDF speichern“.

## Installation

Voraussetzungen: Python 3.12, [uv](https://docs.astral.sh/uv/), `ffmpeg` und `libsndfile`.

```bash
uv sync
```

## Benutzung

Web-Oberfläche (danach http://localhost:8000 öffnen):

```bash
uv run take-check serve
```

Kommandozeile:

```bash
uv run take-check analyze "Song (Rhythm).gp" "Take 25L.wav" -o ergebnis.json
uv run take-check analyze vorlage.musicxml take.wav --tuning "Drop D" --min-confidence 0.6
```

Die Sprache der Kommandozeile richtet sich nach `$LANG`, die der Oberfläche nach den Browser-Einstellungen.

## Weitere Sprache hinzufügen

Alle Texte – Oberfläche, Befunde, Warnungen, Kommandozeile – stehen in einer Datei pro Sprache unter
`src/take_check/locales/` (`de.json`, `en.json`). Für eine neue Sprache:

1. `en.json` kopieren, z. B. nach `fr.json`, und unter `meta` Code (`fr`), Name (`Français`) und
   `date_locale` setzen.
2. Die Texte unter `ui` (Oberfläche) und `msg` (Analyse) übersetzen. Platzhalter wie `{note}` bleiben
   unverändert; Pluralformen sind Objekte nach Intl-Kategorien, z. B. `{"one": "{n} Befund", "other": "{n} Befunde"}`.
3. Server neu starten – die Sprache erscheint automatisch im Sprachmenü und wird anhand der Browser-Sprache gewählt.

Fehlende Einträge fallen auf Englisch zurück. `uv run pytest tests/test_i18n.py` prüft, ob eine Datei vollständig
ist und dieselben Platzhalter verwendet. Analysen speichern Textschlüssel statt fertiger Sätze, daher erscheinen
auch bestehende Analysen in der neuen Sprache.

## Aufbau

- `src/take_check/` – Analyse (Python): Vorlagen-Import (`score/`), Audio-Auswertung (`audio/`), Vergleich,
  KI-Check, Web-API (`api.py`), Übersetzungen (`i18n.py`, `locales/`), Profile (`profile.py`, `profiles/`)
- `web/` – Oberfläche als native ES-Module ohne Build-Schritt: `js/core/` (API, i18n, Formatierung),
  `js/views/home.js`, `js/views/analysis/` (Pianoroll, Befundliste, Tooltips, Bedienung, KI-Check),
  `js/views/report/` (Musiker-Bericht), `css/`, `vendor/alphatab/` (alphaTab 1.8.4, MPL-2.0)

## Tests

```bash
uv run pytest
```

Die End-to-End-Tests erzeugen synthetische Aufnahmen mit gezielt eingebauten Fehlern. Eigene Beispieldateien
gehören nach `data/` (wird nicht versioniert); Analysen der Web-App landen in `analyses/`.
