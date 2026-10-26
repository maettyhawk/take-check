"""Test-Hilfen: MusicXML aus einer kompakten Tab-Beschreibung erzeugen und Noten additiv synthetisieren."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SR = 22050
STEPS = [("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0), ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0)]
TUNING = [40, 45, 50, 55, 59, 64]


@dataclass
class Ev:
    """Ein Ereignis im Takt: Akkord aus (Saite, Bund) oder Pause (leere Liste)."""
    frets: list[tuple[int, int]]
    dur: int                       # in Sechzehnteln (divisions = 4 pro Viertel)
    pm: bool = False
    hammer: bool = False           # Ziel eines Hammer-ons
    bend: float = 0.0              # Halbtöne
    harmonic: bool = False
    dead: bool = False
    extra: dict = field(default_factory=dict)


def _pitch_xml(midi: int) -> str:
    step, alter = STEPS[midi % 12]
    alt = f"<alter>{alter}</alter>" if alter else ""
    return f"<pitch><step>{step}</step>{alt}<octave>{midi // 12 - 1}</octave></pitch>"


def write_musicxml(path, bars: list[list[Ev]], tempo: int = 100) -> None:
    tuning = "".join(
        f'<staff-tuning line="{i + 1}"><tuning-step>{STEPS[p % 12][0]}</tuning-step>'
        f'{"<tuning-alter>1</tuning-alter>" if STEPS[p % 12][1] else ""}<tuning-octave>{p // 12 - 1}</tuning-octave></staff-tuning>'
        for i, p in enumerate(TUNING))
    out = ['<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0">',
           '<work><work-title>Synthetik</work-title></work>',
           '<part-list><score-part id="P1"><part-name>Gitarre</part-name></score-part></part-list><part id="P1">']
    for b, events in enumerate(bars):
        out.append(f'<measure number="{b + 1}">')
        if b == 0:
            out.append('<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time>'
                       f'<staff-details><staff-lines>6</staff-lines>{tuning}</staff-details></attributes>'
                       f'<direction><direction-type><words>Tempo</words></direction-type><sound tempo="{tempo}"/></direction>')
        for ev in events:
            if not ev.frets:
                out.append(f'<note><rest/><duration>{ev.dur}</duration><voice>1</voice></note>')
                continue
            if ev.pm:
                out.append('<direction><direction-type><words>P.M.</words></direction-type></direction>')
            for k, (s, f) in enumerate(ev.frets):
                pitch = TUNING[6 - s] + f
                tech = ""
                if ev.hammer:
                    tech += '<hammer-on type="stop"/>'
                if ev.bend:
                    tech += f"<bend><bend-alter>{ev.bend}</bend-alter></bend>"
                if ev.harmonic:
                    tech += "<harmonic><natural/></harmonic>"
                head = "<notehead>x</notehead>" if ev.dead else ""
                chord = "<chord/>" if k else ""
                out.append(f"<note>{chord}{_pitch_xml(pitch)}<duration>{ev.dur}</duration><voice>1</voice>{head}"
                           f"<notations><technical>{tech}<string>{s}</string><fret>{f}</fret></technical></notations></note>")
        out.append("</measure>")
    out.append("</part></score-partwise>")
    path.write_text("".join(out))


def _hz(midi):
    return 440.0 * 2 ** ((np.asarray(midi) - 69) / 12)


def render_note(pitch: float, duration: float, *, pm=False, legato=False, harmonic=False, dead=False,
                bend: list[tuple[float, float]] | None = None, amp=0.5, rng=None) -> np.ndarray:
    rng = rng or np.random.default_rng(0)
    length = duration + 0.03
    t = np.arange(int(length * SR)) / SR
    semis = np.interp(t, *zip(*bend)) if bend else 0.0
    f0 = _hz(pitch + semis) * np.ones_like(t)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    y = np.zeros_like(t)
    if dead:
        y = rng.standard_normal(len(t)) * np.exp(-t * 60) * 0.3
    else:
        partials = [(1, 1.0), (2, 0.12)] if harmonic else [(k, 1 / k ** 1.1) for k in range(1, 11)]
        for k, a in partials:
            if f0.max() * k > SR / 2 * 0.95:
                break
            decay = (3.0 if harmonic else 1.5 + 0.8 * k) if not pm else 18 + 6 * k
            if pm:
                a *= np.exp(-0.3 * k)
            y += a * np.exp(-t * decay) * np.sin(k * phase)
    ramp = int((0.015 if legato else 0.001) * SR)
    y[:ramp] *= np.linspace(0, 1, ramp)
    if not legato and not dead:
        burst = int(0.004 * SR)
        noise = np.diff(rng.standard_normal(burst + 1))
        y[:burst] += 0.4 * noise * np.linspace(1, 0, burst)
    fade = int(0.03 * SR)
    y[-fade:] *= np.linspace(1, 0, fade)
    return amp * y / max(np.abs(y).max(), 1e-9)


def render(notes, total: float, lead_in: float = 0.0, seed: int = 0) -> np.ndarray:
    """`notes`: Dicts mit onset, duration, pitch und optional pm, legato, harmonic, dead, bend, amp."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int((total + lead_in + 1.0) * SR))
    for n in notes:
        y = render_note(n["pitch"], n["duration"], pm=n.get("pm", False), legato=n.get("legato", False),
                        harmonic=n.get("harmonic", False), dead=n.get("dead", False), bend=n.get("bend"),
                        amp=n.get("amp", 0.4), rng=rng)
        i = int((n["onset"] + lead_in) * SR)
        out[i:i + len(y)] += y[:len(out) - i]
    out += rng.standard_normal(len(out)) * 1e-4
    return (0.9 * out / np.abs(out).max()).astype(np.float32)


def score_to_render(score) -> list[dict]:
    return [{"id": n.id, "onset": n.onset, "duration": n.duration, "pitch": n.pitch, "pm": n.palm_mute,
             "legato": n.legato, "harmonic": bool(n.harmonic), "dead": n.dead, "bend": n.bend} for n in score.notes]
