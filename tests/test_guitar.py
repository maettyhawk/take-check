import pytest

from take_check.score import guitar


@pytest.mark.parametrize("fret, partial", [(12, 2), (7, 3), (19, 3), (5, 4), (24, 4), (4, 5), (9, 5), (3, 6), (2, None)])
def test_natural_harmonic_partial(fret, partial):
    assert guitar.natural_harmonic_partial(fret) == partial


def test_natural_harmonic_pitch_low_e():
    assert guitar.natural_harmonic_pitch(40, 12) == 52
    assert guitar.natural_harmonic_pitch(40, 7) == 59
    assert guitar.natural_harmonic_pitch(40, 5) == 64
    assert guitar.natural_harmonic_pitch(40, 4) == 68


def test_string_numbering_seven_string():
    seven = guitar.parse_tuning("7 standard")
    assert len(seven) == 7
    assert guitar.string_pitch(seven, 7) == 35  # B1
    assert guitar.string_pitch(seven, 1) == 64  # E4
    assert guitar.fretted_pitch(seven, 7, 3, capo=0) == 38


def test_parse_tuning_presets_and_lists():
    assert guitar.parse_tuning("Drop D") == [38, 45, 50, 55, 59, 64]
    assert guitar.parse_tuning("drop-d") == [38, 45, 50, 55, 59, 64]
    assert guitar.parse_tuning("F#1 B1 E2 A2 D3 G3 B3 E4") == guitar.TUNING_PRESETS["8 standard"]
    # hoch → tief angegeben wird umgedreht
    assert guitar.parse_tuning("E4 B3 G3 D3 A2 D2") == [38, 45, 50, 55, 59, 64]
    with pytest.raises(ValueError):
        guitar.parse_tuning("irgendwas")


def test_artificial_harmonic():
    assert guitar.artificial_harmonic_pitch(60) == 72
    assert guitar.artificial_harmonic_pitch(60, touch_offset=7) == 79
