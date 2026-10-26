"""Timing gegen den eigenen Groove: gleichmäßig vor/hinter dem Klick ist Stil, Ausreißer sind Befunde."""

from take_check.audio.transcribe import DetectedNote
from take_check.compare import Issues, NoteResult, Options, timing_issues
from take_check.score.model import Bar, Score, ScoreNote


def _take(lag_by_bar, outlier=None):
    """8 Takte à 8 Achtel (120 BPM); Takt 1–4 im Groove `lag_by_bar[0]`, Takt 5–8 `lag_by_bar[1]`."""
    notes, results = [], []
    for k in range(64):
        t = k * 0.25
        bar = k // 8 + 1
        n = ScoreNote(id=k, onset=t, duration=0.25, pitch=40, bar=bar, beat=1 + (k % 8) / 2)
        lag = lag_by_bar[0] if bar <= 4 else lag_by_bar[1]
        lag += 0.004 * ((k * 7) % 3 - 1)  # etwas menschliche Streuung
        if k == outlier:
            lag += 0.045
        r = NoteResult(n, t, status="ok", det=DetectedNote(k, t + lag, 0.2, 40, 0.6))
        notes.append(n)
        results.append(r)
    score = Score(notes=notes, bars=[Bar(b + 1, 1, b * 2.0, b * 2.0 + 2.0, 4, 4) for b in range(8)])
    issues = Issues(score, 0.0)
    timing_issues(results, Options(timing_tol=0.03), issues)
    return issues


def test_consistent_push_is_a_hint_not_an_error():
    issues = _take((0.020, 0.0))
    assert [i for i in issues.items if i["type"] in ("early", "late")] == []
    assert len(issues.hints) == 1 and "T. 1–4" in str(issues.hints[0]) and "hinter dem Klick" in str(issues.hints[0])


def test_outlier_against_groove_is_reported():
    issues = _take((0.020, 0.0), outlier=20)  # Takt 3: 45 ms später als der eigene Groove
    timing = [i for i in issues.items if i["type"] in ("early", "late")]
    assert len(timing) == 1 and timing[0]["note_id"] == 20 and timing[0]["type"] == "late"
    assert 35 <= timing[0]["delta_ms"] <= 55 and 15 <= timing[0]["groove_ms"] <= 25
