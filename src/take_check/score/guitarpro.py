"""Import nativer Guitar-Pro-Dateien (GP7/GP8, `.gp`: ZIP mit Content/score.gpif).

Gegenüber dem MusicXML-Export bleiben hier die exakten Bend-Kurven (Zeitpunkte in Prozent der Note)
erhalten. Das Ergebnis wird in dieselbe Zwischenstruktur übersetzt wie beim MusicXML-Import, damit
Wiederholungen, Tempo, Haltebögen und Flageoletts identisch behandelt werden.
"""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from ..i18n import msg
from .model import Score
from .musicxml import _Measure, _RawNote, build_score

NOTE_VALUES = {"Whole": 4.0, "Half": 2.0, "Quarter": 1.0, "Eighth": 0.5, "16th": 0.25, "32nd": 0.125,
               "64th": 0.0625, "128th": 0.03125, "256th": 0.015625}
# Tempo-Automation "128 2": zweite Zahl = Bezugsnotenwert
TEMPO_UNIT = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0, 5: 3.0}
BEND_UNIT = 50.0  # GP: 100 = Ganzton


def _ids(text: str | None) -> list[str]:
    return [t for t in (text or "").split() if t != "-1"]


def _props(el: ET.Element) -> dict[str, ET.Element]:
    return {p.get("name"): p for p in el.findall("Properties/Property")}


def _prop_value(prop: ET.Element | None, default=None):
    if prop is None:
        return default
    child = next(iter(prop), None)
    if child is None:
        return True
    if child.tag == "Enable":
        return True
    return (child.text or "").strip()


def _float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_gpif(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as z:
        try:
            data = z.read("Content/score.gpif")
        except KeyError:
            raise ValueError("Keine Guitar-Pro-7/8-Datei (Content/score.gpif fehlt). "
                             "Ältere Formate (.gp3/.gp4/.gp5/.gpx) bitte als MusicXML exportieren.")
    return ET.fromstring(data)


def _bend_points(props: dict[str, ET.Element]) -> list[tuple[float, float]] | None:
    if "Bended" not in props:
        return None
    v = lambda name: _float(_prop_value(props.get(name), 0))  # noqa: E731
    origin = (v("BendOriginOffset"), v("BendOriginValue") / BEND_UNIT)
    dest = (v("BendDestinationOffset") if "BendDestinationOffset" in props else 100.0, v("BendDestinationValue") / BEND_UNIT)
    mid_val = v("BendMiddleValue") / BEND_UNIT
    points = [origin]
    # Mittelpunkte nur, wenn sie ein Extremum bilden (Bend-Release, Release-Bend); bei einfachen
    # Bends sind sie bloß Kurvengriffe des Editors.
    if mid_val > max(origin[1], dest[1]) + 1e-6 or mid_val < min(origin[1], dest[1]) - 1e-6:
        points += [(v("BendMiddleOffset1"), mid_val), (v("BendMiddleOffset2"), mid_val)]
    points.append(dest)
    return sorted(points, key=lambda p: p[0])


def parse_gp(path: str | Path, tuning: list[int] | None = None) -> Score:
    path = Path(path)
    root = load_gpif(path)
    warnings: list[str] = []

    rhythms = {r.get("id"): r for r in root.findall("Rhythms/Rhythm")}
    notes_by_id = {n.get("id"): n for n in root.findall("Notes/Note")}
    beats_by_id = {b.get("id"): b for b in root.findall("Beats/Beat")}
    voices_by_id = {v.get("id"): v for v in root.findall("Voices/Voice")}
    bars_by_id = {b.get("id"): b for b in root.findall("Bars/Bar")}
    master_bars = root.findall("MasterBars/MasterBar")
    tracks = root.findall("Tracks/Track")
    if not tracks or not master_bars:
        raise ValueError("Die Guitar-Pro-Datei enthält keine Spuren oder Takte.")

    def track_has_notes(idx: int) -> bool:
        for mb in master_bars:
            bar_ids = _ids(mb.findtext("Bars"))
            if idx < len(bar_ids):
                for vid in _ids(bars_by_id[bar_ids[idx]].findtext("Voices")):
                    for bid in _ids(voices_by_id[vid].findtext("Beats")):
                        if _ids(beats_by_id[bid].findtext("Notes")):
                            return True
        return False

    candidates = [i for i in range(len(tracks)) if track_has_notes(i)]
    if not candidates:
        raise ValueError("Keine Spur mit Noten gefunden.")
    track_idx = candidates[0]
    track = tracks[track_idx]
    track_name = track.findtext("Name") or f"Spur {track_idx + 1}"
    if len(candidates) > 1:
        warnings.append(msg("score_multiple_tracks", name=track_name))

    pitches = track.find(".//Property[@name='Tuning']/Pitches")
    file_tuning = [int(p) for p in pitches.text.split()] if pitches is not None and pitches.text else None
    if file_tuning is None:
        warnings.append(msg("score_no_tuning_assumed"))
        file_tuning = [40, 45, 50, 55, 59, 64]
    tuning = tuning or file_tuning
    capo = int(_float(track.findtext(".//Property[@name='CapoFret']/Fret"), 0))

    tempo_events: dict[int, list[tuple[float, float]]] = {}
    for auto in root.findall("MasterTrack/Automations/Automation"):
        if auto.findtext("Type") != "Tempo":
            continue
        parts = (auto.findtext("Value") or "120").split()
        bpm = _float(parts[0], 120) * TEMPO_UNIT.get(int(parts[1]) if len(parts) > 1 else 2, 1.0)
        bar = int(_float(auto.findtext("Bar"), 0))
        tempo_events.setdefault(bar, []).append((_float(auto.findtext("Position"), 0), bpm))
        if auto.findtext("Linear") == "true":
            warnings.append(msg("score_tempo_ramp", bar=bar + 1))

    measures: list[_Measure] = []
    ending_block, last_endings = 0, None
    warned_strings = False
    for m_idx, mb in enumerate(master_bars):
        num, den = (mb.findtext("Time") or "4/4").split("/")
        beats, beat_type = int(num), int(den)
        m = _Measure(number=m_idx + 1, length_q=beats * 4 / beat_type, beats=beats, beat_type=beat_type)
        m.tempos = [(pos * m.length_q, bpm) for pos, bpm in tempo_events.get(m_idx, [])]

        rep = mb.find("Repeat")
        if rep is not None:
            m.repeat_forward = rep.get("start") == "true"
            m.repeat_backward = rep.get("end") == "true"
            m.repeat_times = max(int(_float(rep.get("count"), 2)), 2)
        endings = frozenset(int(x) for x in (mb.findtext("AlternateEndings") or "").split() if x.isdigit())
        if endings:
            if endings != last_endings:
                ending_block += 1
            m.ending_block, m.ending_numbers = ending_block, set(endings)
        last_endings = endings or None
        for target in mb.findall("Directions/Target"):
            t = (target.text or "").strip()
            if t in ("Segno", "SegnoSegno"):
                m.segno = t.lower()
            elif t in ("Coda", "DoubleCoda"):
                m.coda = t.lower()
            elif t == "Fine":
                m.fine = True
        for jump in mb.findall("Directions/Jump"):
            j = (jump.text or "").strip()
            if j.startswith("DaCapo"):
                m.dacapo = True
            elif j.startswith("DaSegnoSegno"):
                m.dalsegno = "segnosegno"
            elif j.startswith("DaSegno"):
                m.dalsegno = "segno"
            elif j == "DaCoda":
                m.tocoda = "coda"
            elif j == "DaDoubleCoda":
                m.tocoda = "doublecoda"

        bar_ids = _ids(mb.findtext("Bars"))
        if track_idx < len(bar_ids):
            bar = bars_by_id[bar_ids[track_idx]]
            for v_no, vid in enumerate(_ids(bar.findtext("Voices"))):
                cursor = 0.0
                for bid in _ids(voices_by_id[vid].findtext("Beats")):
                    beat = beats_by_id[bid]
                    rhythm = rhythms[beat.find("Rhythm").get("ref")]
                    dur = NOTE_VALUES.get(rhythm.findtext("NoteValue"), 1.0)
                    dots = rhythm.find("AugmentationDot")
                    if dots is not None:
                        dur *= {1: 1.5, 2: 1.75, 3: 1.875}.get(int(_float(dots.get("count"), 1)), 1.5)
                    tup = rhythm.find("PrimaryTuplet")
                    if tup is not None:
                        dur *= _float(tup.get("den"), 1) / max(_float(tup.get("num"), 1), 1)
                    grace = beat.findtext("GraceNotes") is not None
                    beat_props = _props(beat)
                    for nid in _ids(beat.findtext("Notes")):
                        raw = _note(notes_by_id[nid], cursor, dur, str(v_no + 1), grace, tuning, capo, beat_props)
                        if raw is None:
                            continue
                        if raw.string is None and not warned_strings:
                            warned_strings = True
                            warnings.append(msg("score_more_strings"))
                        m.notes.append(raw)
                    if not grace:
                        cursor += dur
                m.length_q = max(m.length_q, cursor)
        measures.append(m)

    title = root.findtext("Score/Title") or path.stem
    score = build_score(measures, tuning, capo, title.strip() or path.stem, warnings)
    score.track_index = track_idx
    return score


def _note(n: ET.Element, offset_q: float, dur_q: float, voice: str, grace: bool, tuning: list[int], capo: int,
          beat_props: dict[str, ET.Element]) -> _RawNote | None:
    props = _props(n)
    gp_string = _prop_value(props.get("String"))
    fret = int(_float(_prop_value(props.get("Fret")), 0))
    midi = _prop_value(props.get("Midi"))
    string = None
    if gp_string is not None and int(gp_string) < len(tuning):
        s0 = int(gp_string)                    # GP: 0 = tiefste Saite
        string = len(tuning) - s0              # intern: 1 = höchste Saite
        pitch = tuning[s0] + capo + fret
    elif midi is not None:
        pitch = int(_float(midi))
    else:
        return None
    tie = n.find("Tie")
    raw = _RawNote(
        offset_q=offset_q, dur_q=dur_q, pitch=pitch, voice=voice, staff="1", grace=grace,
        tie_start=tie is not None and tie.get("origin") == "true",
        tie_stop=tie is not None and tie.get("destination") == "true",
        string=string, fret=fret,
        palm_mute="PalmMuted" in props,
        legato="HopoDestination" in props,
        slide="Slide" in props,
        vibrato=n.find("Vibrato") is not None or "VibratoWTremBar" in beat_props,
        dead="Muted" in props,
        let_ring=n.find("LetRing") is not None,
        bend_points=_bend_points(props),
    )
    htype = _prop_value(props.get("HarmonicType"))
    if htype:
        h = str(htype).lower()
        hfret = _float(_prop_value(props.get("HarmonicFret")), 12.0)
        if h == "natural":
            raw.harmonic, raw.fret = "natural", hfret if hfret > 0 else fret
        elif h == "pinch":
            raw.harmonic = "pinch"
        else:  # Artificial, Tap, Semi, Feedback
            raw.harmonic, raw.harmonic_offset = "artificial", hfret
    return raw
