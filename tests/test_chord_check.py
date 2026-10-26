"""Systematisch ausgelassene Akkordtöne: herabgestufte Einzelmeldungen plus Warnung mit Taktliste."""

import numpy as np

from take_check.audio import chord_check
from take_check.compare import Issues, NoteResult
from take_check.i18n import render
from take_check.profile import Chords
from take_check.score.model import Bar, Score, ScoreNote


def test_bar_ranges():
    bars = {(8, 1), (9, 1), (10, 1), (13, 1), (20, 1), (21, 1), (9, 2)}
    assert chord_check.bar_ranges(bars) == "8–10, 13, 20–21, 9 (2.)"


def _chord_score(n_chords=24, palm_mute=True):
    """C3–G3–C4–D4 als Achtel; D4 auf Saite 2, C4 ist Oberton von C3."""
    notes, k = [], 0
    for c in range(n_chords):
        t = c * 0.5
        for pitch, string in ((48, 5), (55, 4), (60, 3), (62, 2)):
            notes.append(ScoreNote(id=k, onset=t, duration=0.25, pitch=pitch, bar=c // 4 + 1,
                                   beat=1 + (c % 4), string=string, palm_mute=palm_mute))
            k += 1
    bars = [Bar(b + 1, 1, b * 2.0, b * 2.0 + 2.0, 4, 4) for b in range(n_chords // 4)]
    return Score(notes=notes, bars=bars)


def _top_missing_everywhere(monkeypatch, palm_mute):
    score = _chord_score(palm_mute=palm_mute)
    results, issues = [], Issues(score, 0.0)
    for n in score.notes:
        r = NoteResult(n, n.onset)
        if n.pitch == 62:   # D4 fehlt überall
            issues.add("missing", n.onset, "Fehlende Note: D4", 0.7, n)
        else:
            r.status = "ok"
        results.append(r)
    # gespielte Töne -5 dB, Nachbarn -15 dB, das ausgelassene D4 -20 dB
    played = {48, 55, 60}
    monkeypatch.setattr(chord_check, "salience_db",
                        lambda tracker, pitch, onset, dur: -5.0 if pitch in played else -20.0 if pitch == 62 else -15.0)
    warnings: list[str] = []
    chord_check.evaluate(object(), results, issues, warnings)
    return results, issues, warnings


def test_quiet_upper_tone_in_palm_mute_is_typical_not_an_error(monkeypatch):
    results, issues, warnings = _top_missing_everywhere(monkeypatch, palm_mute=True)
    assert issues.items == [] and warnings == []
    assert len(issues.hints) == 1 and "Typisch für Palm Mute" in render(issues.hints[0], "de") and "Takte: 1–6" in render(issues.hints[0], "de")
    assert all(r.status == "unchecked" for r in results if r.note.pitch == 62)
    # C4 ist Oberton von C3 und wird nicht als fehlend behandelt
    assert all(r.features["masked"] for r in results if r.note.pitch == 60)


def test_systematic_omission_without_palm_mute_is_downgraded_and_warned(monkeypatch):
    results, issues, warnings = _top_missing_everywhere(monkeypatch, palm_mute=False)
    omitted = [i for i in issues.items if i["type"] == "chord_tone_omitted"]
    assert len(omitted) == 24 and all(i["confidence"] <= chord_check.OMITTED_MAX_CONFIDENCE for i in omitted)
    assert not [i for i in issues.items if i["type"] == "missing"]
    assert all(r.status == "omitted" for r in results if r.note.pitch == 62)
    assert len(warnings) == 1 and "Saite 2" in render(warnings[0], "de") and "nicht sicher" in render(warnings[0], "de")


def _occasional(monkeypatch, palm_mute):
    score = _chord_score(palm_mute=palm_mute)
    results, issues = [], Issues(score, 0.0)
    for n in score.notes:
        r = NoteResult(n, n.onset)
        if n.pitch == 62 and n.onset < 1.0:   # nur in zwei Akkorden fehlt das D4
            issues.add("missing", n.onset, "Fehlende Note: D4", 0.7, n)
        else:
            r.status = "ok"
        results.append(r)
    monkeypatch.setattr(chord_check, "salience_db",
                        lambda tracker, pitch, onset, dur: -20.0 if pitch == 62 and onset < 1.0
                        else -5.0 if pitch in (48, 55, 60, 62) else -15.0)
    warnings: list[str] = []
    chord_check.evaluate(object(), results, issues, warnings)
    return results, issues, warnings


def test_occasional_pm_omission_in_full_chord_is_not_claimed(monkeypatch):
    """Palm Mute: Akkord klingt mehrstimmig → einzelner Ton gilt als nicht sicher bestimmbar, keine Meldung."""
    results, issues, warnings = _occasional(monkeypatch, palm_mute=True)
    assert warnings == [] and issues.items == []
    assert [r.status for r in results if r.note.pitch == 62 and r.note.onset < 1.0] == ["unchecked", "unchecked"]


def test_occasional_open_omission_is_reported_cautiously(monkeypatch):
    results, issues, warnings = _occasional(monkeypatch, palm_mute=False)
    assert warnings == []
    missing = [i for i in issues.items if i["type"] == "missing"]
    assert len(missing) == 2 and all(i["confidence"] <= Chords().uncertain_missing_cap for i in missing)
