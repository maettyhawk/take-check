"""End-to-End: synthetische Aufnahme mit eingebauten Fehlern muss die richtigen Befunde liefern."""

import copy

import pytest
import soundfile as sf

from synth import SR, Ev, render, score_to_render, write_musicxml
from take_check.analyze import analyze
from take_check.score import load_score

PM = dict(pm=True)
LEAD_IN = 1.3


def song():
    chug = [Ev([(6, 0)], 2, **PM) for _ in range(4)] + [Ev([(5, 0)], 4), Ev([(4, 0)], 4)]
    return [
        chug, copy.deepcopy(chug), copy.deepcopy(chug), copy.deepcopy(chug),
        [Ev([(3, 0)], 2), Ev([(3, 2)], 2, hammer=True), Ev([(2, 0)], 4), Ev([(2, 1)], 4), Ev([(2, 3)], 4)],
        [Ev([(2, 8)], 8, bend=2), Ev([(3, 7)], 4, harmonic=True), Ev([], 4)],
        [Ev([(6, 0), (5, 2), (4, 2)], 8), Ev([(5, 0)], 4), Ev([(5, 0)], 4, dead=True)],
        [Ev([(4, 2)], 16)],
    ]


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("e2e")
    xml = d / "song.musicxml"
    write_musicxml(xml, song())
    return d, xml, load_score(xml)


def find(notes, bar, beat, pitch=None):
    for n in notes:
        if n["_bar"] == bar and abs(n["_beat"] - beat) < 1e-3 and (pitch is None or n["pitch"] == pitch):
            return n
    raise LookupError((bar, beat, pitch))


def run(d, xml, score, mutate, name):
    notes = score_to_render(score)
    for n, sn in zip(notes, score.notes):
        n["_bar"], n["_beat"] = sn.bar, sn.beat
    notes = mutate(notes)
    wav = d / f"{name}.wav"
    total = max(n["onset"] + n["duration"] for n in notes)
    sf.write(wav, render(notes, total, lead_in=LEAD_IN), SR)
    return analyze(xml, wav)


def types_at(result, bar, min_conf=0.0):
    return {i["type"] for i in result["issues"] if i["bar"] == bar and i["confidence"] >= min_conf}


@pytest.fixture(scope="module")
def clean(files):
    d, xml, score = files
    return run(d, xml, score, lambda ns: ns, "clean")


def faulty_mutation(ns):
    find(ns, 2, 4, 50)["onset"] += 0.07                     # zu spät
    find(ns, 3, 4, 50)["pitch"] = 51                        # falscher Ton
    find(ns, 3, 1)["pm"] = False                            # Palm Mute fehlt
    find(ns, 3, 1.5)["pm"] = False
    ns.remove(find(ns, 4, 3, 45))                           # fehlende Note
    find(ns, 5, 1.5)["legato"] = False                      # angeschlagen statt Hammer-on
    bend = find(ns, 6, 1)
    bend["bend"] = [(t, s * 0.7) for t, s in bend["bend"]]  # Bend zu tief (+1,4 statt +2)
    harm = find(ns, 6, 3)
    harm["pitch"], harm["harmonic"] = 62, False             # gegriffen statt Flageolett
    last = find(ns, 8, 1)
    ns.append({"onset": last["onset"] + 1.2, "duration": 0.4, "pitch": 72})  # zusätzliche Note
    return ns



@pytest.fixture(scope="module")
def faulty(files):
    d, xml, score = files
    return run(d, xml, score, faulty_mutation, "faulty")


def test_offset_detected(clean, faulty):
    assert clean["offset"] == pytest.approx(LEAD_IN, abs=0.02)
    assert faulty["offset"] == pytest.approx(LEAD_IN, abs=0.02)


def test_clean_take_has_no_confident_note_errors(clean):
    serious = [i for i in clean["issues"] if i["confidence"] >= 0.5
               and i["type"] in ("missing", "wrong_pitch", "extra", "early", "late", "bend_missing", "harmonic_fretted")]
    assert serious == []


def test_faulty_take_findings(faulty):
    assert "late" in types_at(faulty, 2, 0.5)
    assert "wrong_pitch" in types_at(faulty, 3, 0.5)
    assert "pm_missing" in types_at(faulty, 3)
    assert "missing" in types_at(faulty, 4, 0.5)
    assert "legato_picked" in types_at(faulty, 5)
    assert "bend_pitch" in types_at(faulty, 6, 0.5)
    assert "harmonic_fretted" in types_at(faulty, 6, 0.5)
    assert "extra" in types_at(faulty, 8, 0.5)
    bend = next(i for i in faulty["issues"] if i["type"] == "bend_pitch")
    assert -80 <= bend["cents"] <= -40
