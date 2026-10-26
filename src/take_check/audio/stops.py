"""Pausen und Stops: Klingt in notierten Pausen noch etwas nach?

Im Mix fallen nicht abgedämpfte Saiten in Stops sofort auf. Gemessen wird der Pegel in jeder Pause
(nach einer kurzen Ausklingzeit, vor dem nächsten Anschlag) relativ zum Spielpegel der Umgebung und zum
Grundrauschen der Aufnahme. Notiertes Let Ring darf in die Pause hineinklingen.
"""

from __future__ import annotations

import numpy as np

from ..compare import Issues, NoteResult, note_name
from ..i18n import msg
from ..profile import Stops
from ..score.model import ScoreNote
from .pitch_contour import PitchTracker

HOP = 256


def _frames_db(y: np.ndarray) -> np.ndarray:
    n = len(y) // HOP
    frames = y[:n * HOP].reshape(n, HOP)
    return 10 * np.log10((frames ** 2).mean(axis=1) + 1e-12)


def expected_rests(notes: list[ScoreNote], offset: float, min_rest: float) -> list[tuple[float, float, float]]:
    """Lücken (Audiozeit), in denen laut Vorlage keine Note klingt, mit der Dauer des längsten Tons davor."""
    spans = []
    by_string: dict = {}
    for n in sorted(notes, key=lambda n: n.onset):
        by_string.setdefault(n.string, []).append(n)
    for n in notes:
        end = n.end
        if n.let_ring:  # klingt bis zum nächsten Ton auf derselben Saite (höchstens 4 s)
            later = [m.onset for m in by_string.get(n.string, []) if m.onset > n.onset + 1e-4]
            end = min(later[0] if later else n.onset + 4.0, n.onset + 4.0)
        spans.append((n.onset + offset, end + offset))
    spans.sort()
    rests, cur_end, last_len = [], None, 0.0
    for start, end in spans:
        if cur_end is not None and start - cur_end >= min_rest:
            rests.append((cur_end, start, last_len))
        if cur_end is None or end >= cur_end:
            last_len = end - start
        cur_end = end if cur_end is None else max(cur_end, end)
    return rests


def evaluate(y: np.ndarray, sr: int, tracker: PitchTracker, notes: list[ScoreNote], results: list[NoteResult],
             offset: float, issues: Issues, warnings: list[str], cfg: Stops) -> None:
    if not cfg.enabled:
        return
    db = _frames_db(y)
    t_frames = (np.arange(len(db)) + 0.5) * HOP / sr
    floor = float(np.percentile(db, 5))
    attacks = np.array([r.onset for r in results if r.det is not None and not r.weak])
    if not len(attacks):
        return
    attack_db = np.array([db[max(int(t * sr / HOP), 0):int((t + 0.1) * sr / HOP) + 1].max(initial=-120) for t in attacks])

    measured = []
    for start, end, held in expected_rests(notes, offset, cfg.min_rest_ms / 1000):
        a, b = start + cfg.release_ms / 1000, end - cfg.anticipation_ms / 1000
        if b - a < 0.06:
            continue
        sel = (t_frames >= a) & (t_frames <= b)
        if sel.sum() < 3:
            continue
        level = float(np.percentile(db[sel], 90))
        near = np.abs(attacks - start) <= 4.0
        play = float(np.median(attack_db[near])) if near.sum() >= 3 else float(np.median(attack_db))
        measured.append((start, end, a, b, level, level - play, held))
    if len(measured) < 3:
        return
    rel = np.array([m[5] for m in measured])
    med = float(np.median(rel))
    mad = max(float(np.median(np.abs(rel - med))) * 1.4826, 2.0)
    if med > cfg.max_level_db:
        warnings.append(msg("rests_ringing_general", db=f"{abs(med):.0f}"))
    for start, end, a, b, level, r, held in measured:
        if r <= cfg.max_level_db or level - floor < cfg.min_above_floor_db or r - med <= cfg.outlier_mad * mad:
            continue
        ringing = _ringing_pitch(y, sr, a, b, min(n.pitch for n in notes))
        what = msg("rest_ringing_note", note=note_name(ringing)) if ringing else ""
        conf = float(np.clip(0.5 + (r - cfg.max_level_db) / 30, 0.5, 0.85))
        message = msg("rest_ringing", db=f"{abs(r):.0f}", ringing=what, ms=f"{(end - start) * 1000:.0f}")
        if held >= cfg.natural_decay_after_s:
            # lang gehaltener Ton, der natürlich ausklingt: oft bewusste Phrasierung
            conf *= cfg.natural_decay_factor
            message += msg("rest_decay_suffix")
        issues.add("rest_ringing", start, message,
                   conf, None, None, level_db=round(r, 1),
                   rest_end=round(end, 4), played_pitch=ringing)


def _ringing_pitch(y: np.ndarray, sr: int, a: float, b: float, lowest: int) -> int | None:
    """Klingender Ton in der Pause per Obertonsumme – nur aus dem Signal der Pause selbst.

    (Die CQT mittelt in tiefen Lagen über fast eine Sekunde und sähe noch den Akkord davor.)
    """
    seg = y[int(a * sr):int(b * sr)]
    if len(seg) < 1024:
        return None
    n_fft = 1 << int(np.ceil(np.log2(max(len(seg), 8192))))
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n_fft))
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)

    def at(f: float) -> float:
        k = int(round(f / freqs[1]))
        return float(spec[max(k - 2, 0):k + 3].max()) if k + 3 < len(spec) else 0.0

    candidates = range(max(lowest - 2, 21), 89)
    weights = (1.0, 0.8, 0.6, 0.5, 0.4)
    sal = np.array([sum(w * at(440 * 2 ** ((p - 69) / 12) * (k + 1)) for k, w in enumerate(weights)) for p in candidates])
    best = int(np.argmax(sal))
    if sal[best] < 3 * float(np.median(sal)):
        return None
    # Bei Akkorden den tiefsten klingenden Ton nennen: tiefster Kandidat mit deutlichem eigenen Grundton
    fundamentals = np.array([at(440 * 2 ** ((p - 69) / 12)) for p in candidates])
    for k in range(best + 1):
        if fundamentals[k] >= 0.35 * fundamentals.max() and sal[k] >= 0.5 * sal[best]:
            return int(candidates[k])
    return int(candidates[best])
