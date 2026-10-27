"""MusicXML-Import (partwise, auch komprimiert als .mxl) mit Fokus auf Guitar-Pro-Exporte.

Ausgewertet werden u. a. Akkorde, Haltebögen, Wiederholungen/Voltas, D.C./D.S./Coda/Fine, Tempowechsel,
Tabulatur (Saite/Bund, Stimmung, Kapodaster), Palm Mute, Hammer-on/Pull-off, Slides, Bends, Flageoletts,
Vibrato und Dead Notes.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

from . import guitar
from ..i18n import msg
from .model import Bar, Score, ScoreNote

STEP_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
PM_WORDS = re.compile(r"^\s*(p\.?\s*m\.?|palm\s*mute)\s*[-.\s]*$", re.IGNORECASE)
GRACE_DURATION = 0.05  # Sekunden
DEFAULT_TEMPO = 120.0


@dataclass
class _Bend:
    alter: float
    pre: bool = False
    release: bool = False
    first: float | None = None  # Prozent der Notendauer
    last: float | None = None


@dataclass
class _RawNote:
    offset_q: float
    dur_q: float
    pitch: int | None
    voice: str
    staff: str
    grace: bool = False
    tie_start: bool = False
    tie_stop: bool = False
    string: int | None = None
    fret: int | None = None
    palm_mute: bool = False
    legato: bool = False
    slur_stop: bool = False
    slide: bool = False
    vibrato: bool = False
    dead: bool = False
    let_ring: bool = False
    harmonic: str | None = None
    harmonic_written: str = "base"  # base | sounding | touching
    harmonic_offset: float = 12     # künstliche Flageoletts: Antippen so viele Bünde über dem Griff
    bends: list[_Bend] = field(default_factory=list)
    bend_points: list[tuple[float, float]] | None = None  # (Prozent der Notendauer, Halbtöne) – exakt, aus .gp


@dataclass
class _Measure:
    number: int
    length_q: float
    beats: int
    beat_type: int
    notes: list[_RawNote] = field(default_factory=list)
    tempos: list[tuple[float, float]] = field(default_factory=list)
    repeat_forward: bool = False
    repeat_backward: bool = False
    repeat_times: int = 2
    ending_block: int | None = None
    ending_numbers: set[int] = field(default_factory=set)
    segno: str | None = None
    coda: str | None = None
    dacapo: bool = False
    dalsegno: str | None = None
    tocoda: str | None = None
    fine: bool = False


def _load_root(path: Path) -> ET.Element:
    if path.suffix.lower() == ".mxl" or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            name = None
            if "META-INF/container.xml" in z.namelist():
                container = ET.fromstring(z.read("META-INF/container.xml"))
                rootfile = container.find(".//rootfile")
                if rootfile is not None:
                    name = rootfile.get("full-path")
            if name is None:
                name = next(n for n in z.namelist() if n.endswith(".xml") and not n.startswith("META-INF"))
            return _strip_ns(_parse_xml(z.read(name)))
    return _strip_ns(_parse_xml(path.read_bytes()))


def _parse_xml(data: bytes) -> ET.Element:
    # Processing-Instructions behalten: Guitar Pro legt z. B. Vibrato als <?GP <root>…</root>?> ab
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_pis=True))
    parser.feed(data)
    return parser.close()


def _gp_instructions(note_el: ET.Element) -> list[ET.Element]:
    """Inhalt der Guitar-Pro-Processing-Instructions einer Note als Elemente."""
    out = []
    for el in note_el.iter():
        if el.tag is ET.ProcessingInstruction and (el.text or "").startswith("GP"):
            try:
                out.extend(ET.fromstring(el.text[2:].strip()).iter())
            except ET.ParseError:
                pass
    return out


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _int(text: str | None, default: int = 0) -> int:
    try:
        return int(float(text)) if text is not None else default
    except ValueError:
        return default


def _float(text: str | None, default: float | None = None) -> float | None:
    try:
        return float(text) if text is not None else default
    except ValueError:
        return default


def _pitch(el: ET.Element) -> int | None:
    p = el.find("pitch")
    if p is None:
        return None
    step = p.findtext("step", "C")
    alter = _float(p.findtext("alter"), 0.0) or 0.0
    octave = _int(p.findtext("octave"), 4)
    return (octave + 1) * 12 + STEP_SEMITONES[step] + round(alter)


def _choose_part(root: ET.Element) -> tuple[ET.Element, str]:
    parts = root.findall("part")
    if not parts:
        raise ValueError("Keine <part>-Elemente gefunden – nur MusicXML 'score-partwise' wird unterstützt.")
    names = {sp.get("id"): (sp.findtext("part-name") or "") for sp in root.iter("score-part")}

    def rank(part: ET.Element) -> tuple[int, int]:
        has_tab = int(part.find(".//staff-tuning") is not None or part.find(".//technical/fret") is not None)
        n_pitched = sum(1 for n in part.iter("note") if n.find("pitch") is not None)
        return has_tab, n_pitched

    best = max(parts, key=rank)
    return best, names.get(best.get("id"), "")


def _choose_staff(part: ET.Element) -> str | None:
    """Bei Notensystem + TAB im selben Part: das System mit Saite/Bund-Angaben verwenden."""
    counts: dict[str, int] = {}
    for n in part.iter("note"):
        staff = n.findtext("staff")
        if staff is not None and n.find("notations/technical/fret") is not None:
            counts[staff] = counts.get(staff, 0) + 1
    if counts:
        return max(counts, key=counts.get)
    staves = {n.findtext("staff") for n in part.iter("note") if n.findtext("staff")}
    return "1" if len(staves) > 1 else None


def _parse_technical(note_el: ET.Element, raw: _RawNote) -> None:
    for tech in note_el.findall("notations/technical"):
        for child in tech:
            tag = child.tag
            if not isinstance(tag, str):  # Processing-Instruction
                continue
            if tag == "string":
                raw.string = _int(child.text) or None
            elif tag == "fret":
                raw.fret = _int(child.text)
            elif tag in ("hammer-on", "pull-off") and child.get("type") == "stop":
                raw.legato = True
            elif tag == "bend":
                raw.bends.append(_Bend(
                    alter=_float(child.findtext("bend-alter"), 0.0) or 0.0,
                    pre=child.find("pre-bend") is not None,
                    release=child.find("release") is not None,
                    first=_float(child.get("first-beat")),
                    last=_float(child.get("last-beat")),
                ))
            elif tag == "harmonic":
                raw.harmonic = "artificial" if child.find("artificial") is not None else "natural"
                if child.find("sounding-pitch") is not None:
                    raw.harmonic_written = "sounding"
                elif child.find("touching-pitch") is not None:
                    raw.harmonic_written = "touching"
            elif "palm" in tag or (tag == "other-technical" and child.text and PM_WORDS.match(child.text)):
                raw.palm_mute = True
            elif tag == "other-technical" and child.text:
                text = child.text.lower()
                if "pinch" in text or text.strip() in ("p.h.", "ph"):
                    raw.harmonic = "pinch"
                elif "vibrato" in text:
                    raw.vibrato = True


def _parse_part(part: ET.Element, staff_filter: str | None, warnings: list[str],
                tuning_override: list[int] | None = None):
    measures: list[_Measure] = []
    pm_events: list[tuple[tuple[int, float], str, str]] = []  # ((Takt, Offset), kind, dashes-Nummer)
    divisions = 1
    beats, beat_type = 4, 4
    tuning: list[int] | None = tuning_override
    capo = 0
    warned_strings = False
    transpose = 0
    ending_counter = 0
    open_ending: tuple[int, set[int]] | None = None
    has_hammer_tags = part.find(".//hammer-on") is not None or part.find(".//pull-off") is not None
    slur_starts: dict[str, int | None] = {}

    for m_idx, m_el in enumerate(part.findall("measure")):
        cursor = 0
        max_cursor = 0
        last_onset = 0
        m = _Measure(number=_int(m_el.get("number"), m_idx + 1), length_q=0, beats=beats, beat_type=beat_type)
        if open_ending is not None:
            m.ending_block, m.ending_numbers = open_ending[0], set(open_ending[1])

        for el in m_el:
            tag = el.tag
            if tag == "attributes":
                divisions = _int(el.findtext("divisions"), divisions) or divisions
                if el.find("time") is not None:
                    beats = _int(el.findtext("time/beats"), beats) or beats
                    beat_type = _int(el.findtext("time/beat-type"), beat_type) or beat_type
                    m.beats, m.beat_type = beats, beat_type
                for sd in el.findall("staff-details"):
                    if staff_filter is not None and sd.get("number", staff_filter) != staff_filter:
                        continue
                    lines = sd.findall("staff-tuning")
                    if lines and tuning_override is None:
                        by_line = {}
                        for t in lines:
                            step = t.findtext("tuning-step", "E")
                            alter = round(_float(t.findtext("tuning-alter"), 0.0) or 0.0)
                            octave = _int(t.findtext("tuning-octave"), 2)
                            by_line[_int(t.get("line"), 1)] = (octave + 1) * 12 + STEP_SEMITONES[step] + alter
                        tuning = [by_line[k] for k in sorted(by_line)]
                    if sd.findtext("capo"):
                        capo = _int(sd.findtext("capo"))
                tr = el.find("transpose")
                if tr is not None:
                    transpose = _int(tr.findtext("chromatic")) + 12 * _int(tr.findtext("octave-change"))
            elif tag == "note":
                if el.find("cue") is not None:
                    continue
                staff = el.findtext("staff", "1")
                is_chord = el.find("chord") is not None
                grace = el.find("grace") is not None
                dur = _int(el.findtext("duration"))
                onset = last_onset if is_chord else cursor
                if not is_chord and not grace:
                    last_onset = cursor
                    cursor += dur
                    max_cursor = max(max_cursor, cursor)
                if el.find("rest") is not None:
                    continue
                if staff_filter is not None and staff != staff_filter:
                    continue
                written = _pitch(el)
                raw = _RawNote(
                    offset_q=onset / divisions,
                    dur_q=dur / divisions,
                    pitch=None if written is None else written + transpose,
                    voice=el.findtext("voice", "1"),
                    staff=staff,
                    grace=grace,
                    tie_start=any(t.get("type") == "start" for t in el.findall("tie")),
                    tie_stop=any(t.get("type") == "stop" for t in el.findall("tie")),
                    dead=(el.findtext("notehead") or "").strip() == "x",
                )
                _parse_technical(el, raw)
                for gp in _gp_instructions(el):
                    if gp.tag == "vibrato":
                        raw.vibrato = True
                    elif gp.tag.lower() in ("letring", "let-ring"):
                        raw.let_ring = True
                    elif "palm" in gp.tag.lower():
                        raw.palm_mute = True
                if el.find("notations/ornaments/wavy-line") is not None or el.find("notations/ornaments/vibrato") is not None:
                    raw.vibrato = True
                if any("let ring" in (t.text or "").lower() for t in el.iter("other-technical")):
                    raw.let_ring = True
                if el.find("notations/slide[@type='start']") is not None or el.find("notations/glissando[@type='start']") is not None:
                    raw.slide = True
                for slur in el.findall("notations/slur"):
                    num = slur.get("number", "1")
                    if slur.get("type") == "start":
                        slur_starts[num] = raw.pitch
                    elif slur.get("type") == "stop" and num in slur_starts:
                        if slur_starts.pop(num) != raw.pitch:
                            raw.slur_stop = True
                if not has_hammer_tags and raw.slur_stop:
                    raw.legato = True
                if raw.string and raw.fret is not None and tuning:
                    if raw.string <= len(tuning):
                        raw.pitch = guitar.fretted_pitch(tuning, raw.string, raw.fret, capo)
                    elif not warned_strings:
                        warned_strings = True
                        warnings.append(msg("score_string_exceeds", string=raw.string, strings=len(tuning)))
                m.notes.append(raw)
            elif tag == "backup":
                cursor -= _int(el.findtext("duration"))
            elif tag == "forward":
                cursor += _int(el.findtext("duration"))
                max_cursor = max(max_cursor, cursor)
            elif tag in ("direction", "sound"):
                offset = _int(el.findtext("offset")) if tag == "direction" else 0
                pos = (cursor + offset) / divisions
                sounds = [el] if tag == "sound" else el.findall("sound")
                for snd in sounds:
                    if snd.get("tempo"):
                        m.tempos.append((pos, float(snd.get("tempo"))))
                    if snd.get("segno"):
                        m.segno = snd.get("segno")
                    if snd.get("coda"):
                        m.coda = snd.get("coda")
                    if snd.get("dacapo") == "yes":
                        m.dacapo = True
                    if snd.get("dalsegno"):
                        m.dalsegno = snd.get("dalsegno")
                    if snd.get("tocoda"):
                        m.tocoda = snd.get("tocoda")
                    if snd.get("fine"):
                        m.fine = True
                if tag == "direction":
                    words = " ".join((w.text or "") for w in el.iter("words"))
                    dashes = el.find("direction-type/dashes")
                    if el.find("direction-type/segno") is not None and m.segno is None:
                        m.segno = "segno"
                    if el.find("direction-type/coda") is not None and m.coda is None and not words.strip():
                        m.coda = "coda"
                    if PM_WORDS.match(words or ""):
                        if dashes is not None and dashes.get("type") == "start":
                            pm_events.append(((m_idx, pos), "start", dashes.get("number", "1")))
                        else:
                            pm_events.append(((m_idx, pos), "single", ""))
                    elif dashes is not None and dashes.get("type") == "stop":
                        pm_events.append(((m_idx, pos), "stop", dashes.get("number", "1")))
            elif tag == "barline":
                rep = el.find("repeat")
                if rep is not None:
                    if rep.get("direction") == "forward":
                        m.repeat_forward = True
                    elif rep.get("direction") == "backward":
                        m.repeat_backward = True
                        m.repeat_times = _int(rep.get("times"), 2) or 2
                end = el.find("ending")
                if end is not None:
                    nums = {int(x) for x in re.findall(r"\d+", end.get("number", ""))}
                    if end.get("type") == "start":
                        ending_counter += 1
                        open_ending = (ending_counter, nums)
                        m.ending_block, m.ending_numbers = ending_counter, nums
                    elif end.get("type") in ("stop", "discontinue"):
                        open_ending = None

        timesig_q = m.beats * 4 / m.beat_type
        content_q = max_cursor / divisions
        m.length_q = content_q if m_el.get("implicit") == "yes" and content_q > 0 else max(timesig_q, content_q)
        measures.append(m)

    _apply_palm_mute_ranges(measures, pm_events)
    return measures, tuning, capo


def _apply_palm_mute_ranges(measures: list[_Measure], events) -> None:
    open_ranges: dict[str, tuple[int, float]] = {}
    ranges: list[tuple[tuple[int, float], tuple[int, float]]] = []
    for pos, kind, num in events:
        if kind == "single":
            ranges.append((pos, pos))
        elif kind == "start":
            open_ranges[num] = pos
        elif kind == "stop" and num in open_ranges:
            ranges.append((open_ranges.pop(num), pos))
    for start in open_ranges.values():  # nicht geschlossen: bis Taktende
        ranges.append((start, (start[0], float("inf"))))
    eps = 1e-6
    for m_idx, m in enumerate(measures):
        for n in m.notes:
            p = (m_idx, n.offset_q)
            if any((a[0], a[1] - eps) <= p <= (b[0], b[1] + eps) for a, b in ranges):
                n.palm_mute = True


def _expand(measures: list[_Measure]) -> list[int]:
    """Spielreihenfolge der Takte (Wiederholungen, Voltas, D.C./D.S., Coda, Fine)."""
    seq: list[int] = []
    n = len(measures)
    segno_idx = {m.segno: i for i, m in enumerate(measures) if m.segno}
    coda_idx = {m.coda: i for i, m in enumerate(measures) if m.coda}
    i, repeat_start, pass_no = 0, 0, 1
    taken: dict[int, int] = {}
    jumped: set[int] = set()
    after_jump = False
    guard = 0
    while i < n and guard < 100_000:
        guard += 1
        m = measures[i]
        if m.repeat_forward and repeat_start != i:
            repeat_start, pass_no = i, 1
        if m.ending_block is not None and m.ending_numbers and pass_no not in m.ending_numbers:
            block = m.ending_block
            while i < n and measures[i].ending_block == block:
                i += 1
            continue
        seq.append(i)
        if m.repeat_backward and not after_jump:
            done = taken.get(i, 0)
            if done < m.repeat_times - 1:
                taken[i] = done + 1
                pass_no += 1
                i = repeat_start
                continue
            pass_no = 1
            repeat_start = i + 1
        if after_jump and m.fine:
            break
        if after_jump and m.tocoda and m.tocoda in coda_idx:
            i = coda_idx[m.tocoda]
            after_jump = False
            continue
        if i not in jumped and (m.dacapo or m.dalsegno):
            jumped.add(i)
            after_jump = True
            i = segno_idx.get(m.dalsegno, 0) if m.dalsegno else 0
            continue
        i += 1
    return seq


class _TempoMap:
    def __init__(self, events: list[tuple[float, float]]):
        events = sorted(events)
        if not events or events[0][0] > 0:
            events.insert(0, (0.0, events[0][1] if events else DEFAULT_TEMPO))
        # Bei mehreren Ereignissen an derselben Stelle gilt das letzte
        dedup: dict[float, float] = {}
        for q, bpm in events:
            dedup[q] = bpm
        self.q = sorted(dedup)
        self.bpm = [dedup[q] for q in self.q]
        self.sec = [0.0]
        for k in range(1, len(self.q)):
            self.sec.append(self.sec[-1] + (self.q[k] - self.q[k - 1]) * 60 / self.bpm[k - 1])

    def to_seconds(self, q: float) -> float:
        k = bisect_right(self.q, q) - 1
        k = max(k, 0)
        return self.sec[k] + (q - self.q[k]) * 60 / self.bpm[k]


def _bend_curve(bends: list[_Bend], duration: float, start_level: float = 0.0) -> tuple[list[tuple[float, float]], float]:
    points: list[tuple[float, float]] = [(0.0, start_level)]
    cur = start_level
    count = len(bends)
    for k, b in enumerate(bends):
        seg0 = duration * k / count
        seg1 = duration * (k + 1) / count
        if b.pre:
            cur = b.alter
            points = [(0.0, cur)] if k == 0 else points + [(seg0, cur)]
            continue
        t0 = duration * b.first / 100 if b.first is not None else seg0
        t1 = duration * b.last / 100 if b.last is not None else seg0 + 0.5 * (seg1 - seg0)
        if b.release:  # Guitar Pro schreibt Release-Ziel 0 als <bend-alter>0</bend-alter><release/>
            target = 0.0 if b.alter == 0 else max(cur - abs(b.alter), 0.0)
        else:
            target = max(cur + b.alter, 0.0)
        points += [(t0, cur), (max(t1, t0), target)]
        cur = target
    points.append((duration, cur))
    return points, cur


def _raw_curve(raw: _RawNote, duration: float, start_level: float = 0.0) -> tuple[list[tuple[float, float]], float]:
    if raw.bend_points:
        points = [(pct / 100 * duration, semis) for pct, semis in raw.bend_points]
        if points[0][0] > 0:
            points.insert(0, (0.0, points[0][1]))
        if points[-1][0] < duration:
            points.append((duration, points[-1][1]))
        return points, points[-1][1]
    return _bend_curve(raw.bends, duration, start_level)


def parse_musicxml(path: str | Path, tuning: list[int] | None = None) -> Score:
    path = Path(path)
    root = _load_root(path)
    if root.tag == "score-timewise":
        raise ValueError("MusicXML 'score-timewise' wird nicht unterstützt – bitte als 'partwise' exportieren.")
    warnings: list[str] = []
    part, part_name = _choose_part(root)
    if len(root.findall("part")) > 1:
        name = part_name or part.get("id")
        warnings.append(msg("score_multiple_tracks", name=name))
    staff_filter = _choose_staff(part)
    measures, tuning, capo = _parse_part(part, staff_filter, warnings, tuning)
    if tuning is None:
        warnings.append(msg("score_no_tuning"))
    title = root.findtext("work/work-title") or root.findtext("movement-title") or path.stem
    score = build_score(measures, tuning, capo, title, warnings)
    score.track_index = root.findall("part").index(part)
    return score


def build_score(measures: list[_Measure], tuning: list[int] | None, capo: int, title: str,
                warnings: list[str]) -> Score:
    """Gemeinsamer Teil aller Importe: Spielreihenfolge, Tempo → Sekunden, Haltebögen, Flageoletts."""
    seq = _expand(measures)

    # Absolute Lage jedes Takts in Viertelnoten + Tempo-Ereignisse in Spielreihenfolge
    starts_q: list[float] = []
    tempo_events: list[tuple[float, float]] = []
    q = 0.0
    for idx in seq:
        starts_q.append(q)
        tempo_events += [(q + off, bpm) for off, bpm in measures[idx].tempos]
        q += measures[idx].length_q
    tempo = _TempoMap(tempo_events)

    bars: list[Bar] = []
    occurrences: dict[int, int] = {}
    pending: list[tuple[ScoreNote, _RawNote]] = []
    for idx, start_q in zip(seq, starts_q):
        m = measures[idx]
        occ = occurrences[idx] = occurrences.get(idx, 0) + 1
        bars.append(Bar(m.number, occ, tempo.to_seconds(start_q), tempo.to_seconds(start_q + m.length_q),
                        m.beats, m.beat_type))
        for raw in m.notes:
            if raw.pitch is None:
                continue
            abs_q = start_q + raw.offset_q
            onset = tempo.to_seconds(abs_q)
            duration = tempo.to_seconds(abs_q + raw.dur_q) - onset
            if raw.grace:
                onset, duration = max(onset - GRACE_DURATION, 0.0), GRACE_DURATION
            note = ScoreNote(
                id=0, onset=onset, duration=duration, pitch=raw.pitch, bar=m.number,
                beat=round(1 + raw.offset_q / (4 / m.beat_type), 3), occurrence=occ,
                string=raw.string, fret=raw.fret, palm_mute=raw.palm_mute, legato=raw.legato,
                slide=raw.slide, vibrato=raw.vibrato, dead=raw.dead, let_ring=raw.let_ring,
            )
            _apply_harmonic(note, raw, tuning, capo)
            pending.append((note, raw))

    notes = _merge_ties(pending)
    notes = _dedupe(notes)
    notes.sort(key=lambda n: (n.onset, n.pitch))
    for k, n in enumerate(notes):
        n.id = k
    if not notes:
        warnings.append(msg("score_no_notes"))
    return Score(notes=notes, bars=bars, tuning=tuning, title=title, warnings=warnings)


def _apply_harmonic(note: ScoreNote, raw: _RawNote, tuning: list[int] | None, capo: int) -> None:
    if raw.harmonic is None:
        return
    note.harmonic = raw.harmonic
    has_tab = raw.string is not None and raw.fret is not None
    if raw.harmonic == "natural":
        if has_tab and raw.fret > 0 and (raw.harmonic_written == "base" or tuning):
            if tuning and raw.string <= len(tuning):
                open_pitch = guitar.string_pitch(tuning, raw.string) + capo
            else:  # ohne Stimmung: notierte Tonhöhe = gegriffene Tonhöhe über dem Bund
                open_pitch = note.pitch - raw.fret
            sounding = guitar.natural_harmonic_pitch(open_pitch, raw.fret)
            note.fretted_pitch = open_pitch + round(raw.fret)
            if sounding is not None:
                note.pitch = sounding
        elif raw.harmonic_written != "sounding":
            note.alt_pitches = [note.pitch + i for i in (12, 19, 24)]
    else:
        fretted = note.pitch
        note.fretted_pitch = fretted
        if raw.harmonic == "artificial" and raw.harmonic_written != "sounding":
            note.pitch = guitar.artificial_harmonic_pitch(fretted, round(raw.harmonic_offset))
        if raw.harmonic == "pinch":
            note.pitch = fretted + guitar.PINCH_INTERVALS[1]
        note.alt_pitches = [fretted + i for i in guitar.PINCH_INTERVALS if fretted + i != note.pitch]


def _merge_ties(pending: list[tuple[ScoreNote, _RawNote]]) -> list[ScoreNote]:
    pending.sort(key=lambda p: (p[0].onset, p[0].pitch))
    open_ties: dict[tuple, tuple[ScoreNote, float]] = {}  # key → (Note, aktuelles Bend-Niveau)
    out: list[ScoreNote] = []
    for note, raw in pending:
        key = (raw.pitch, raw.string, raw.voice)
        if raw.tie_stop and key in open_ties:
            first, level = open_ties[key]
            shift = note.onset - first.onset
            if raw.bends or raw.bend_points:
                curve, level = _raw_curve(raw, note.duration, level)
                first.bend = (first.bend or [(0.0, 0.0)]) + [(t + shift, s) for t, s in curve]
            elif first.bend:
                first.bend.append((shift + note.duration, level))
            first.duration = note.end - first.onset
            if raw.tie_start:
                open_ties[key] = (first, level)
            else:
                del open_ties[key]
            continue
        level = 0.0
        if raw.bends or raw.bend_points:
            note.bend, level = _raw_curve(raw, note.duration)
            note.bend_timed = raw.bend_points is not None or all(
                b.pre or (b.first is not None and b.last is not None) for b in raw.bends)
        out.append(note)
        if raw.tie_start:
            open_ties[key] = (note, level)
    return out


def _dedupe(notes: list[ScoreNote]) -> list[ScoreNote]:
    """Doppelte Noten (z. B. Notensystem + TAB ohne Staff-Angabe) zusammenfassen."""
    best: dict[tuple[float, int], ScoreNote] = {}
    for n in notes:
        key = (round(n.onset, 3), n.pitch)
        if key not in best or (best[key].string is None and n.string is not None):
            best[key] = n
    return list(best.values())
