"""Pausen/Stops: eine in die Pause hineinklingende Saite wird gefunden, sauber abgedämpfte nicht."""

import pytest
import soundfile as sf

from synth import SR, Ev, render, score_to_render, write_musicxml
from take_check.analyze import analyze
from take_check.score import load_score


@pytest.fixture(scope="module")
def stop_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("stops")
    xml = d / "stops.musicxml"
    riff = [Ev([(6, 0), (5, 2)], 4), Ev([], 4), Ev([(6, 3), (5, 5)], 4), Ev([], 4)]  # Akkord – Pause – Akkord – Pause
    write_musicxml(xml, [list(riff) for _ in range(8)], tempo=100)
    return d, xml, load_score(xml)


def _run(d, xml, score, ring_bar=None):
    notes = score_to_render(score)
    for n, sn in zip(notes, score.notes):
        n["amp"] = 0.4
        if sn.bar == ring_bar and sn.beat == 3:
            n["duration"] += 0.45  # klingt in die folgende Pause hinein
    wav = d / f"stops_{ring_bar}.wav"
    total = max(n["onset"] + n["duration"] for n in notes)
    sf.write(wav, render(notes, total, lead_in=0.5), SR)
    return analyze(xml, wav)


def test_clean_stops_have_no_findings(stop_files):
    result = _run(*stop_files)
    assert [i for i in result["issues"] if i["type"] == "rest_ringing"] == []


def test_ringing_rest_is_found(stop_files):
    result = _run(*stop_files, ring_bar=5)
    ringing = [i for i in result["issues"] if i["type"] == "rest_ringing"]
    assert len(ringing) == 1, ringing
    assert ringing[0]["bar"] == 5 and ringing[0]["beat"] == pytest.approx(4, abs=0.1)
    assert ringing[0]["played_pitch"] == 43  # tiefster klingender Ton: G2 (Saite 6, Bund 3)
