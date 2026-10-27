"""Schnelle Bends auf tiefen Saiten zwischen gleich hohen Chugs; Bends auf leeren Saiten nur als Hinweis."""

import numpy as np

from synth import render

from take_check.audio.pitch_contour import PitchTracker, evaluate_bends
from take_check.audio.transcribe import DetectedNote
from take_check.compare import Issues, NoteResult
from take_check.score.model import Bar, Score, ScoreNote

SR = 22050
E2 = 40
BEND_AT = 1.0


def _setup(played_bend, fret=5):
    """E2-Chugs, dann ein E2 mit Bend (+2 in 80 ms laut Vorlage), dann wieder Chugs."""
    notes = [{"onset": 0.2 + 0.2 * k, "duration": 0.15, "pitch": E2, "pm": True} for k in range(4)]
    notes.append({"onset": BEND_AT, "duration": 0.6, "pitch": E2, "bend": played_bend})
    notes += [{"onset": 1.7 + 0.2 * k, "duration": 0.15, "pitch": E2, "pm": True} for k in range(4)]
    y = render(notes, 2.8)
    note = ScoreNote(id=0, onset=BEND_AT, duration=0.6, pitch=E2, bar=1, beat=3.0, string=6, fret=fret,
                     bend=[(0.0, 0.0), (0.08, 2.0), (0.6, 2.0)], bend_timed=True)
    score = Score(title="t", notes=[note], bars=[Bar(number=1, occurrence=1, start=0.0, end=2.8, beats=4, beat_type=4)])
    result = NoteResult(note=note, expected_onset=BEND_AT, status="ok",
                        det=DetectedNote(id=0, onset=BEND_AT, duration=0.6, pitch=E2, amplitude=0.7))
    issues = Issues(score, 0.0)
    evaluate_bends(PitchTracker(y, SR, E2 - 5), [result], issues, 0.0, 30)
    return result, issues.items


def test_fast_low_bend_is_recognised():
    result, items = _setup([(0.0, 0.0), (0.08, 2.0), (0.6, 2.0)])
    assert not [i for i in items if i["type"] in ("bend_missing", "bend_pitch")], items
    assert result.features["bend_reached"] > 1.7


def test_missing_low_bend_still_reported():
    _, items = _setup(None)
    assert [i["type"] for i in items] == ["bend_missing"]
    assert items[0]["confidence"] >= 0.7


def test_open_string_bend_only_hint():
    _, items = _setup(None, fret=0)
    assert [i["type"] for i in items] == ["bend_missing"]
    assert items[0]["confidence"] <= 0.3 and items[0]["msg"]["k"] == "bend_missing_open"
    assert np.isfinite(items[0]["cents"])
