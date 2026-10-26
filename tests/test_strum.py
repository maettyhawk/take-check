"""Anschlagsrichtung: Down-/Upstrokes erkennen, Saitenreihenfolge nicht als Timingfehler werten."""

import pytest
import soundfile as sf

from synth import SR, Ev, render, score_to_render, write_musicxml
from take_check.analyze import analyze
from take_check.score import load_score

STEP = 0.010  # s zwischen zwei Saiten
LATE = 0.060


@pytest.fixture(scope="module")
def strum_result(tmp_path_factory):
    d = tmp_path_factory.mktemp("strum")
    xml = d / "strum.musicxml"
    chord = [(4, 2), (3, 2), (2, 3), (1, 2)]  # E3 A3 D4 F#4 (Saiten 4–1)
    write_musicxml(xml, [[Ev(chord, 4) for _ in range(4)] for _ in range(6)], tempo=90)
    score = load_score(xml)
    notes = score_to_render(score)
    for n, sn in zip(notes, score.notes):
        idx = round(sn.onset / (60 / 90))            # Viertel-Index
        rank_from_low = 4 - sn.string                # Saite 4 = 0 … Saite 1 = 3
        down = idx % 2 == 0
        n["onset"] += (rank_from_low if down else 3 - rank_from_low) * STEP
        n["amp"] = 0.3
        if idx == 9:
            n["onset"] += LATE
    total = max(n["onset"] + n["duration"] for n in notes)
    wav = d / "strum.wav"
    sf.write(wav, render(notes, total, lead_in=0.5), SR)
    from take_check.profile import load_profile
    profile = load_profile()
    profile.strum.show_direction = True  # Erkennung testen, auch wenn sie standardmäßig ausgeblendet ist
    return analyze(xml, wav, profile=profile)


def test_directions_detected(strum_result):
    leads = sorted((n for n in strum_result["notes"] if n["chord_lead"]), key=lambda n: n["onset"])
    assert len(leads) == 24
    correct = sum(1 for k, n in enumerate(leads) if n["strum"]["dir"] == ("down" if k % 2 == 0 else "up"))
    assert correct >= 20, [n["strum"] for n in leads]


def test_strum_order_is_not_a_timing_error(strum_result):
    timing = [i for i in strum_result["issues"] if i["type"] in ("early", "late")]
    assert len(timing) == 1, timing
    late = timing[0]
    assert late["chord"] and late["bar"] == 3 and late["beat"] == 2
    assert late["delta_ms"] == pytest.approx(LATE * 1000, abs=15)
