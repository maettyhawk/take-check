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

## Tests

```bash
uv run pytest
```

Die End-to-End-Tests erzeugen synthetische Aufnahmen mit gezielt eingebauten Fehlern. Eigene Beispieldateien
gehören nach `data/` (wird nicht versioniert); Analysen der Web-App landen in `analyses/`.
