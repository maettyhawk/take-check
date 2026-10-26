"""Flageolett-Prüfung über den Klang: reine, obertonarme Spektren vs. gegriffene Noten.

Die Tonhöhenprüfung (gegriffen statt Flageolett bei z. B. 5./7. Bund) passiert bereits im Vergleich.
Hier geht es um die Fälle, in denen gegriffene Note und Flageolett gleich hoch klingen
(12./24. Bund) – dann hilft nur das Spektrum. Experimentell, daher niedrige Konfidenz.
"""

from __future__ import annotations

import numpy as np

from ..compare import Issues, NoteResult, note_name
from ..i18n import msg
from .pitch_contour import BPO, PitchTracker

PARTIAL_BINS = [round(BPO * np.log2(k)) for k in range(1, 9)]


def purity(tracker: PitchTracker, pitch: int, onset: float) -> float:
    """Anteil der Energie in Teilton 1–2 an Teilton 1–8 zwischen 50 und 250 ms nach dem Anschlag."""
    i0, i1 = np.searchsorted(tracker.times, [onset + 0.05, onset + 0.25])
    b0 = int(round((pitch - tracker.base) * BPO / 12))
    if i1 <= i0 or b0 < 1:
        return float("nan")
    energies = []
    for off in PARTIAL_BINS:
        b = b0 + off
        if b + 1 >= tracker.C.shape[0]:
            break
        energies.append(float((tracker.C[b - 1:b + 2, i0:i1].max(axis=0) ** 2).mean()))
    if len(energies) < 4:
        return float("nan")
    e = np.array(energies)
    return float(e[:2].sum() / e.sum())


def evaluate(tracker: PitchTracker, results: list[NoteResult], issues: Issues) -> None:
    normal = []
    for r in results:
        n = r.note
        if r.status == "ok" and r.det is not None and not n.harmonic and not n.dead and not n.palm_mute:
            v = purity(tracker, n.pitch, r.onset)
            if np.isfinite(v):
                normal.append((n.pitch, v))
    for r in results:
        n = r.note
        if not n.harmonic or r.status != "ok" or r.det is None:
            continue
        v = purity(tracker, r.det.pitch, r.onset)
        r.features["purity"] = None if not np.isfinite(v) else round(v, 3)
        same_pitch = n.fretted_pitch is not None and r.det.pitch == n.fretted_pitch
        if not same_pitch or not np.isfinite(v):
            continue
        ref = [pv for p, pv in normal if abs(p - r.det.pitch) <= 7]
        if len(ref) < 5:
            continue
        if v <= float(np.median(ref)):
            issues.add("harmonic_timbre", r.onset,
                       msg("harmonic_timbre", note=note_name(r.det.pitch)),
                       0.35, n, r.det)
