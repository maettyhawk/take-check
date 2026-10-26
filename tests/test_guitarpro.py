"""GP7/8-Import: synthetische score.gpif-Datei und – falls vorhanden – Abgleich mit dem MusicXML-Export."""

import zipfile
from pathlib import Path

import pytest

from take_check.score import load_score

DATA = Path(__file__).parent.parent / "data"


def _prop(name, inner):
    return f'<Property name="{name}">{inner}</Property>'


def _gp(tmp_path, notes_xml, beats, voices, bars, masterbars, rhythms, automations):
    gpif = f"""<?xml version="1.0" encoding="utf-8"?><GPIF>
      <Score><Title><![CDATA[GP-Test]]></Title></Score>
      <MasterTrack><Automations>{automations}</Automations></MasterTrack>
      <Tracks><Track id="0"><Name>Gitarre</Name><Staves><Staff><Properties>
        {_prop("Tuning", "<Pitches>38 45 50 55 59 64</Pitches>")}{_prop("CapoFret", "<Fret>0</Fret>")}
      </Properties></Staff></Staves></Track></Tracks>
      <MasterBars>{masterbars}</MasterBars><Bars>{bars}</Bars><Voices>{voices}</Voices>
      <Beats>{beats}</Beats><Notes>{notes_xml}</Notes><Rhythms>{rhythms}</Rhythms></GPIF>"""
    path = tmp_path / "test.gp"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Content/score.gpif", gpif)
    return path


def note(nid, string, fret, *extra, tie=None):
    tie_xml = f'<Tie origin="{tie[0]}" destination="{tie[1]}"/>' if tie else ""
    return (f'<Note id="{nid}">{tie_xml}<Properties>{_prop("String", f"<String>{string}</String>")}'
            f'{_prop("Fret", f"<Fret>{fret}</Fret>")}{"".join(extra)}</Properties></Note>')


@pytest.fixture
def gp_file(tmp_path):
    notes = "".join([
        note(0, 0, 0, _prop("PalmMuted", "<Enable/>")),                     # Drop-D-Saite leer, PM
        note(1, 3, 2),                                                     # A3
        note(2, 3, 4, _prop("HopoDestination", "<Enable/>")),             # B3 per Hammer-on
        note(3, 4, 7, _prop("Bended", "<Enable/>"),                        # Bend + Release
             _prop("BendOriginOffset", "<Float>0</Float>"), _prop("BendOriginValue", "<Float>0</Float>"),
             _prop("BendMiddleOffset1", "<Float>25</Float>"), _prop("BendMiddleOffset2", "<Float>50</Float>"),
             _prop("BendMiddleValue", "<Float>100</Float>"),
             _prop("BendDestinationOffset", "<Float>90</Float>"), _prop("BendDestinationValue", "<Float>0</Float>")),
        note(4, 5, 7, _prop("HarmonicType", "<HType>Natural</HType>"), _prop("HarmonicFret", "<HFret>7</HFret>")),
        note(5, 2, 3, tie=("true", "false")),
        note(6, 2, 3, tie=("false", "true")),
        note(7, 1, 0, _prop("Muted", "<Enable/>")),
    ])
    rhythms = ('<Rhythm id="0"><NoteValue>Eighth</NoteValue></Rhythm><Rhythm id="1"><NoteValue>Quarter</NoteValue></Rhythm>'
               '<Rhythm id="2"><NoteValue>Half</NoteValue></Rhythm>'
               '<Rhythm id="3"><NoteValue>Eighth</NoteValue><PrimaryTuplet num="3" den="2"/></Rhythm>')
    beats = "".join([
        '<Beat id="0"><Rhythm ref="0"/><Notes>0</Notes></Beat>',
        '<Beat id="1"><Rhythm ref="0"/><Notes>1</Notes></Beat>',
        '<Beat id="2"><Rhythm ref="1"/><Notes>2</Notes></Beat>',
        '<Beat id="3"><Rhythm ref="2"/><Notes>3</Notes></Beat>',
        '<Beat id="4"><Rhythm ref="3"/><Notes>4</Notes></Beat>',
        '<Beat id="5"><Rhythm ref="3"/></Beat>',
        '<Beat id="6"><Rhythm ref="3"/><Notes>7</Notes></Beat>',
        '<Beat id="7"><Rhythm ref="2"/><Notes>5</Notes></Beat>',
        '<Beat id="8"><Rhythm ref="2"/><Notes>6</Notes></Beat>',
        '<Beat id="9"><Rhythm ref="2"/></Beat>',
    ])
    voices = '<Voice id="0"><Beats>0 1 2 3</Beats></Voice><Voice id="1"><Beats>4 5 6 7</Beats></Voice><Voice id="2"><Beats>8 9</Beats></Voice>'
    bars = ('<Bar id="0"><Voices>0 -1 -1 -1</Voices></Bar><Bar id="1"><Voices>1 -1 -1 -1</Voices></Bar>'
            '<Bar id="2"><Voices>2 -1 -1 -1</Voices></Bar>')
    masterbars = ('<MasterBar><Time>4/4</Time><Bars>0</Bars><Repeat start="true" end="true" count="2"/></MasterBar>'
                  '<MasterBar><Time>4/4</Time><Bars>1</Bars></MasterBar>'
                  '<MasterBar><Time>4/4</Time><Bars>2</Bars></MasterBar>')
    autos = ('<Automation><Type>Tempo</Type><Linear>false</Linear><Bar>0</Bar><Position>0</Position><Value>120 2</Value></Automation>'
             '<Automation><Type>Tempo</Type><Linear>false</Linear><Bar>1</Bar><Position>0.5</Position><Value>60 2</Value></Automation>')
    return _gp(tmp_path, notes, beats, voices, bars, masterbars, rhythms, autos)


def at(score, t):
    return sorted((n for n in score.notes if abs(n.onset - t) < 1e-3), key=lambda n: n.pitch)


def test_gp_structure_and_tempo(gp_file):
    s = load_score(gp_file)
    assert s.title == "GP-Test" and s.tuning == [38, 45, 50, 55, 59, 64]
    assert [(b.number, b.occurrence) for b in s.bars] == [(1, 1), (1, 2), (2, 1), (3, 1)]
    # Takt 2: erste Hälfte 120 BPM (1 s), zweite Hälfte 60 BPM (2 s)
    assert s.bars[2].start == pytest.approx(4.0) and s.bars[2].end == pytest.approx(7.0)


def test_gp_techniques(gp_file):
    s = load_score(gp_file)
    pm = at(s, 0.0)[0]
    assert pm.pitch == 38 and pm.palm_mute and pm.string == 6
    assert at(s, 0.5)[0].legato and at(s, 0.5)[0].pitch == 59
    bend = at(s, 1.0)[0]
    assert bend.pitch == 66 and bend.bend_timed
    assert bend.bend == [(0.0, 0.0), (0.25, 2.0), (0.5, 2.0), (0.9, 0.0), (1.0, 0.0)]


def test_gp_tuplets_harmonic_dead_and_tie(gp_file):
    s = load_score(gp_file)
    harm = at(s, 4.0)[0]
    assert harm.harmonic == "natural" and harm.pitch == 64 + 19 and harm.fretted_pitch == 71
    dead = at(s, 4.0 + 2 / 6)[0]  # Triolenachtel: 1/3 Viertel = 1/6 s
    assert dead.dead
    tied = at(s, 4.5)[0]          # nach drei Triolenachteln (= 1 Viertel); D-Saite (Drop D) Bund 3
    # gebunden bis Ende der Halben in Takt 3: 0,5 s (120 BPM) + 2 s (60 BPM, bis Taktende) + 2 s
    assert tied.pitch == 53 and tied.duration == pytest.approx(4.5)


@pytest.mark.skipif(not (DATA / "Das Vergessen (Lead).gp").exists(), reason="Beispieldateien nicht vorhanden")
def test_gp_matches_musicxml_export():
    gp = load_score(DATA / "Das Vergessen (Lead).gp")
    mx = load_score(DATA / "Das Vergessen (Lead).xml")
    assert len(gp.notes) == len(mx.notes)
    for a, b in zip(gp.notes, mx.notes):
        assert (a.pitch, a.bar, a.beat, a.string, a.fret, a.vibrato) == (b.pitch, b.bar, b.beat, b.string, b.fret, b.vibrato)
        assert a.onset == pytest.approx(b.onset, abs=1e-3) and a.duration == pytest.approx(b.duration, abs=1e-3)
