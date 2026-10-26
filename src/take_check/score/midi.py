"""MIDI-Fallback: nur Noten, Tempo und Taktart – keine Artikulation."""

from __future__ import annotations

from pathlib import Path

import mido

from ..i18n import msg
from .model import Bar, Score, ScoreNote


def parse_midi(path: str | Path) -> Score:
    mid = mido.MidiFile(str(path))
    tpb = mid.ticks_per_beat
    tempo_events: list[tuple[int, int]] = [(0, 500_000)]
    timesigs: list[tuple[int, int, int]] = [(0, 4, 4)]
    tracks_notes: list[list[tuple[int, int, int]]] = []

    for track in mid.tracks:
        tick = 0
        active: dict[tuple[int, int], int] = {}
        notes: list[tuple[int, int, int]] = []
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                tempo_events.append((tick, msg.tempo))
            elif msg.type == "time_signature":
                timesigs.append((tick, msg.numerator, msg.denominator))
            elif msg.type == "note_on" and msg.velocity > 0:
                if msg.channel != 9:
                    active[(msg.channel, msg.note)] = tick
            elif msg.type in ("note_off", "note_on"):
                start = active.pop((msg.channel, msg.note), None)
                if start is not None:
                    notes.append((start, tick, msg.note))
        if notes:
            tracks_notes.append(notes)

    warnings = [msg("midi_no_articulation")]
    if not tracks_notes:
        return Score(notes=[], bars=[], warnings=warnings + [msg("midi_no_notes")])
    if len(tracks_notes) > 1:
        warnings.append(msg("midi_multiple_tracks"))
    raw = max(tracks_notes, key=len)

    tempo_events.sort()
    timesigs.sort()

    def to_sec(tick: int) -> float:
        sec, last_tick, tempo = 0.0, 0, 500_000
        for t, tp in tempo_events:
            if t > tick:
                break
            sec += (t - last_tick) * tempo / tpb / 1e6
            last_tick, tempo = t, tp
        return sec + (tick - last_tick) * tempo / tpb / 1e6

    end_tick = max(e for _, e, _ in raw)
    bars: list[Bar] = []
    bar_starts: list[tuple[int, int, int, int]] = []  # (Tick, Länge, Zähler, Nenner)
    tick, number, ts_idx = 0, 1, 0
    while tick <= end_tick:
        while ts_idx + 1 < len(timesigs) and timesigs[ts_idx + 1][0] <= tick:
            ts_idx += 1
        _, num, den = timesigs[ts_idx]
        length = int(num * tpb * 4 / den)
        bar_starts.append((tick, length, num, den))
        bars.append(Bar(number, 1, to_sec(tick), to_sec(tick + length), num, den))
        tick += length
        number += 1

    notes: list[ScoreNote] = []
    for start, end, pitch in sorted(raw):
        k = max(i for i, b in enumerate(bar_starts) if b[0] <= start)
        b_tick, _, _, den = bar_starts[k]
        beat = 1 + (start - b_tick) / (tpb * 4 / den)
        onset = to_sec(start)
        notes.append(ScoreNote(id=len(notes), onset=onset, duration=to_sec(end) - onset, pitch=pitch,
                               bar=k + 1, beat=round(beat, 3)))
    return Score(notes=notes, bars=bars, title=Path(path).stem, warnings=warnings)
