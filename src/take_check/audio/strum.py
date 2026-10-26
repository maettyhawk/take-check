"""Anschlagsrichtung bei Akkorden (Plektrum): Downstroke ↓ = tiefe Saiten zuerst, Upstroke ↑ = hohe zuerst.

Pro Akkordton wird der Einsatz aus der Onset-Aktivierung von Basic Pitch für genau diese Tonhöhe bestimmt
(Frame-Raster ~11,6 ms, parabolisch interpoliert). Die Reihenfolge der Einsätze über die Saiten ergibt die
Richtung; sehr kleine Spreizungen bleiben „gleichzeitig“, weil sie unter der Messgenauigkeit liegen.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from ..compare import Issues, NoteResult, note_name
from ..i18n import tr
from ..profile import Strum
from .transcribe import MIDI_OFFSET, Transcription

MIN_ORDER_CORR = 0.7


def chord_groups(results: list[NoteResult]) -> list[list[NoteResult]]:
    by_onset: dict[float, list[NoteResult]] = defaultdict(list)
    for r in results:
        if not r.note.dead:
            by_onset[round(r.expected_onset, 3)].append(r)
    return [g for g in by_onset.values() if len(g) >= 2]


def _low_to_high(r: NoteResult) -> float:
    """Sortierschlüssel tiefe → hohe Saite (Saite 1 = höchste); ohne Tab nach Tonhöhe."""
    return -r.note.string if r.note.string else r.note.pitch


def onset_peak(trans: Transcription, pitch: int, t0: float, t1: float, min_value: float = 0.15) -> float | None:
    col = pitch - MIDI_OFFSET
    if not 0 <= col < trans.onset_post.shape[1]:
        return None
    i0, i1 = np.searchsorted(trans.frame_times, [t0, t1])
    if i1 - i0 < 1:
        return None
    seg = trans.onset_post[i0:i1, col]
    k = int(np.argmax(seg))
    if seg[k] < min_value:
        return None
    t = float(trans.frame_times[i0 + k])
    if 0 < k < len(seg) - 1:
        a, b, c = seg[k - 1], seg[k], seg[k + 1]
        denom = a - 2 * b + c
        if abs(denom) > 1e-9:
            step = float(trans.frame_times[i0 + k + 1] - trans.frame_times[i0 + k])
            t += float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5)) * step
    return t


def _rank_corr(x: list[float], y: list[float]) -> float:
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    if np.std(rx) == 0 or np.std(ry) == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def evaluate(results: list[NoteResult], trans: Transcription, issues: Issues, cfg: Strum | None = None) -> None:
    cfg = cfg or Strum()
    min_spread, slow = cfg.min_spread_ms / 1000, cfg.slow_ms / 1000
    for g in chord_groups(results):
        played = [r for r in g if r.status == "ok" and r.det is not None and not r.weak]
        if not played:
            continue
        attack = min(r.onset for r in played)
        times = {}
        for r in g:
            if r.status == "ok" and r.det is not None:
                t = onset_peak(trans, r.note.pitch, attack - 0.03, attack + 0.09)
                if t is not None:
                    times[r.note.id] = (r, t)
        direction, spread = None, 0.0
        if len(times) >= 2:
            entries = sorted(times.values(), key=lambda e: _low_to_high(e[0]))
            ts = [t for _, t in entries]
            spread = max(ts) - min(ts)
            corr = _rank_corr(list(range(len(ts))), ts)
            if spread >= min_spread and abs(corr) >= MIN_ORDER_CORR:
                direction = "down" if corr > 0 else "up"
            first = min(ts)
            for r, t in entries:
                r.features["strum_offset_ms"] = round((t - first) * 1000, 1)
        info = {"dir": direction, "spread_ms": round(spread * 1000, 1), "attack": round(attack, 4)}
        for r in g:
            r.strum = info
        if cfg.report_slow and len(times) >= 3 and spread > slow:
            lead = min(played, key=lambda r: r.onset)
            arrow = {"down": " ↓", "up": " ↑"}.get(direction, "")
            names = "·".join(note_name(r.note.pitch) for r in sorted(g, key=lambda r: r.note.pitch))
            issues.add("slow_strum", attack,
                       tr(f"Akkordanschlag verschleppt: {spread * 1000:.0f} ms von erster bis letzter Saite ({names}{arrow})",
                          f"Dragged strum: {spread * 1000:.0f} ms from first to last string ({names}{arrow})"),
                       0.35, lead.note, lead.det, delta_ms=round(spread * 1000))
