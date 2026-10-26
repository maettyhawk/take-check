"""Globaler Versatz zwischen Vorlage und Aufnahme (Einspielung zum Klick → konstanter Versatz)."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from ..score.model import ScoreNote
from .transcribe import DetectedNote


def estimate_offset(score_notes: list[ScoreNote], detected: list[DetectedNote],
                    search: tuple[float, float] = (-5.0, 20.0), step: float = 0.01,
                    tol: float = 0.04) -> tuple[float, float]:
    """Versatz (Audiozeit = Vorlagenzeit + Versatz) und Anteil der dabei passenden Noten.

    Für jeden Kandidatenversatz wird gezählt, wie viele Vorlagennoten eine erkannte Note gleicher
    Tonhöhe innerhalb von `tol` haben. Ein schwacher Prior (erste erkannte vs. erste notierte Note)
    entscheidet bei wiederholten Riffs, die um ganze Takte verschoben fast gleich gut passen.
    """
    notes = [n for n in score_notes if not n.dead]
    if not notes or not detected:
        return 0.0, 0.0
    det_by_pitch: dict[int, np.ndarray] = defaultdict(lambda: np.empty(0))
    tmp: dict[int, list[float]] = defaultdict(list)
    for d in detected:
        tmp[d.pitch].append(d.onset)
    for p, ons in tmp.items():
        det_by_pitch[p] = np.sort(np.array(ons))

    lags = np.arange(search[0], search[1] + step / 2, step)
    counts = np.zeros(len(lags))
    score_by_pitch: dict[int, list[float]] = defaultdict(list)
    for n in notes:
        for p in {n.pitch, *n.alt_pitches}:
            score_by_pitch[p].append(n.onset)
    for p, ons in score_by_pitch.items():
        d = det_by_pitch.get(p)
        if d is None or not len(d):
            continue
        targets = np.array(ons)[:, None] + lags[None, :]
        idx = np.clip(np.searchsorted(d, targets), 1, len(d) - 1)
        dist = np.minimum(np.abs(d[idx] - targets), np.abs(d[idx - 1] - targets))
        if len(d) == 1:
            dist = np.abs(d[0] - targets)
        counts += (dist <= tol).sum(axis=0)

    prior = min(d.onset for d in detected) - min(n.onset for n in notes)
    objective = counts - 0.02 * np.abs(lags - prior)
    best = float(lags[int(np.argmax(objective))])

    # Feinjustierung: Median der Abweichungen der passenden Noten
    deltas = []
    for n in notes:
        d = det_by_pitch.get(n.pitch)
        if d is None or not len(d):
            continue
        t = n.onset + best
        k = int(np.argmin(np.abs(d - t)))
        if abs(d[k] - t) <= tol:
            deltas.append(d[k] - t)
    if deltas:
        best += float(np.median(deltas))
    return round(best, 4), len(deltas) / len(notes)
