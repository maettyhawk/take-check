from pathlib import Path

import pytest

from take_check.i18n import render
from take_check.score import load_score
from take_check.score.musicxml import _expand, _Measure

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def score():
    return load_score(FIXTURES / "riff.musicxml")


def by_time(score, t, tol=1e-3):
    return sorted((n for n in score.notes if abs(n.onset - t) < tol), key=lambda n: n.pitch)


def test_repeat_and_voltas_expand_to_four_bars(score):
    assert [(b.number, b.occurrence) for b in score.bars] == [(1, 1), (2, 1), (1, 2), (3, 1)]
    assert [round(b.start, 3) for b in score.bars] == [0, 2, 4, 6]
    assert score.title == "Testriff"
    assert score.tuning == [40, 45, 50, 55, 59, 64]


def test_palm_mute_range_includes_stop_note(score):
    pm = [n for n in score.notes if n.palm_mute]
    assert [round(n.onset, 2) for n in pm] == [0, 0.25, 0.5, 0.75, 4, 4.25, 4.5, 4.75]
    assert not any(n.palm_mute for n in by_time(score, 1.0))


def test_chord_and_pitch_from_tab(score):
    chord = by_time(score, 1.0)
    assert [n.pitch for n in chord] == [52, 59]
    assert chord[0].bar == 1 and chord[0].beat == 3


def test_tie_across_barline_is_merged(score):
    g = by_time(score, 1.5)
    assert len(g) == 1 and g[0].pitch == 55
    assert g[0].duration == pytest.approx(1.0)
    assert not by_time(score, 2.0)


def test_hammer_on_target_is_legato(score):
    a, b = by_time(score, 2.5)[0], by_time(score, 2.75)[0]
    assert not a.legato and b.legato and b.pitch == 59


def test_bend_with_release(score):
    n = by_time(score, 6.0)[0]
    assert n.pitch == 66 and n.bend_max == pytest.approx(2)
    assert n.bend[0] == (0.0, 0.0)
    assert n.bend[-1][1] == pytest.approx(0.0)
    assert n.bend[-1][0] == pytest.approx(1.0)


def test_natural_harmonic_sounding_pitch(score):
    n = by_time(score, 7.0)[0]
    assert n.harmonic == "natural"
    assert n.fretted_pitch == 71
    assert n.pitch == 83  # E4 + Duodezime


def test_grace_and_dead_note(score):
    grace = by_time(score, 7.45)
    assert grace and grace[0].duration == pytest.approx(0.05)
    dead = by_time(score, 7.5)[0]
    assert dead.dead and dead.pitch == 45


def test_tuning_override_changes_pitches_from_tab():
    drop_d = load_score(FIXTURES / "riff.musicxml", tuning=[38, 45, 50, 55, 59, 64])
    assert by_time(drop_d, 0.0)[0].pitch == 38


def test_seven_string_tab(tmp_path):
    xml = (FIXTURES / "riff.musicxml").read_text()
    seven = xml.replace(
        '<staff-lines>6</staff-lines>',
        '<staff-lines>7</staff-lines>\n          <staff-tuning line="0"><tuning-step>B</tuning-step><tuning-octave>1</tuning-octave></staff-tuning>',
    ).replace("<string>6</string><fret>0</fret>", "<string>7</string><fret>0</fret>", 1)
    p = tmp_path / "seven.musicxml"
    p.write_text(seven)
    s = load_score(p)
    assert len(s.tuning) == 7
    assert by_time(s, 0.0)[0].pitch == 35
    assert by_time(s, 0.25)[0].pitch == 40


def test_without_tuning_uses_written_pitch(tmp_path):
    xml = (FIXTURES / "riff.musicxml").read_text()
    import re
    stripped = re.sub(r"<staff-tuning.*?</staff-tuning>", "", xml, flags=re.S)
    p = tmp_path / "notuning.musicxml"
    p.write_text(stripped)
    s = load_score(p)
    assert s.tuning is None
    assert any("Keine Stimmung" in render(w, "de") for w in s.warnings)
    assert by_time(s, 0.0)[0].pitch == 40
    assert by_time(s, 7.0)[0].pitch == 83  # Flageolett aus notierter Tonhöhe − Bund berechnet


def _m(**kw):
    return _Measure(number=kw.pop("number"), length_q=4, beats=4, beat_type=4, **kw)


def test_expand_dal_segno_al_coda_and_fine():
    ms = [
        _m(number=1),
        _m(number=2, segno="s"),
        _m(number=3, tocoda="c"),
        _m(number=4, dalsegno="s"),
        _m(number=5, coda="c"),
    ]
    assert [ms[i].number for i in _expand(ms)] == [1, 2, 3, 4, 2, 3, 5]
    ms = [_m(number=1), _m(number=2, fine=True), _m(number=3, dacapo=True)]
    assert [ms[i].number for i in _expand(ms)] == [1, 2, 3, 1, 2]


def test_expand_repeat_times():
    ms = [_m(number=1, repeat_forward=True), _m(number=2, repeat_backward=True, repeat_times=3), _m(number=3)]
    assert [ms[i].number for i in _expand(ms)] == [1, 2, 1, 2, 1, 2, 3]
