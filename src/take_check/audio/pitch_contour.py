"""Hochauflösender Tonhöhenverlauf (CQT, 60 Bins/Oktave) für Bends, Vibrato und Stimmung."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

from ..compare import Issues, NoteResult, note_name
from ..i18n import msg

BPO = 60
HARMONIC_BINS = (0, 60, 95)  # 1., 2., 3. Teilton
HARMONIC_WEIGHTS = (1.0, 0.5, 0.33)
OPEN_STRING_CONF = 0.3  # Bends auf leeren Saiten: nur per Tremolo/Whammy möglich → nur als Hinweis


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


class PitchTracker:
    def __init__(self, y: np.ndarray, sr: int, min_pitch: int, hop: int = 256):
        import librosa

        self.base = min_pitch - 2
        n_octaves = min(8, int(np.log2((sr / 2 * 0.9) / _hz(self.base))))
        self.C = np.abs(librosa.cqt(y, sr=sr, hop_length=hop, fmin=_hz(self.base),
                                    n_bins=BPO * n_octaves, bins_per_octave=BPO)).astype(np.float32)
        self.times = librosa.times_like(self.C, sr=sr, hop_length=hop)

    def contour(self, t0: float, t1: float, lo: float, hi: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Zeitpunkte, Tonhöhe (MIDI, gebrochen) und Stärke des stärksten Peaks im Band [lo, hi]."""
        i0, i1 = np.searchsorted(self.times, [t0, t1])
        b_lo = max(int(round((lo - self.base) * BPO / 12)), 1)
        b_hi = min(int(round((hi - self.base) * BPO / 12)), self.C.shape[0] - 2)
        if i1 <= i0 or b_hi <= b_lo:
            return np.empty(0), np.empty(0), np.empty(0)
        S = np.zeros((b_hi - b_lo + 1, i1 - i0), dtype=np.float32)
        for off, w in zip(HARMONIC_BINS, HARMONIC_WEIGHTS):
            if b_hi + off < self.C.shape[0]:
                S += w * self.C[b_lo + off:b_hi + off + 1, i0:i1]
        k = np.argmax(S, axis=0)
        strength = S[k, np.arange(S.shape[1])]
        # parabolische Interpolation zwischen Nachbarbins
        left = S[np.clip(k - 1, 0, len(S) - 1), np.arange(S.shape[1])]
        right = S[np.clip(k + 1, 0, len(S) - 1), np.arange(S.shape[1])]
        denom = left - 2 * strength + right
        frac = np.where(np.abs(denom) > 1e-9, 0.5 * (left - right) / denom, 0.0)
        bins = b_lo + k + np.clip(frac, -0.5, 0.5)
        pitch = self.base + bins * 12 / BPO
        return self.times[i0:i1], pitch, strength

    def note_contour(self, start: float, end: float, lo: float, hi: float) -> tuple[np.ndarray, np.ndarray]:
        t, p, s = self.contour(start, end, lo, hi)
        if not len(t):
            return t, p
        keep = s >= 0.15 * s.max()  # ausgeklungene Frames verwerfen
        t, p = t[keep], p[keep]
        if len(p) >= 5:
            p = median_filter(p, size=5, mode="nearest")
        return t, p


def _is_single(r: NoteResult, results_by_time: list[NoteResult]) -> bool:
    n = r.note
    return not any(o is not r and o.note.onset < n.end and n.onset < o.note.end for o in results_by_time)


def estimate_tuning(tracker: PitchTracker, results: list[NoteResult]) -> float | None:
    """Mittlere Abweichung (Cent) gehaltener Einzelnoten ohne Bend/Vibrato von der gleichstufigen Stimmung."""
    devs = []
    for r in results:
        n = r.note
        if r.status != "ok" or r.det is None or r.weak or n.bend or n.vibrato or n.harmonic or n.dead or n.duration < 0.15:
            continue
        t, p = tracker.note_contour(r.onset + 0.05, r.onset + min(n.duration, 0.6), n.pitch - 0.6, n.pitch + 0.6)
        if len(p) >= 4:
            devs.append(float(np.median(p)) - n.pitch)
    if len(devs) < 5:
        return None
    return round(float(np.median(devs)) * 100, 1)


def evaluate_bends(tracker: PitchTracker, results: list[NoteResult], issues: Issues, tuning_cents: float,
                   tol_cents: float) -> None:
    tune = tuning_cents / 100
    for r in results:
        n = r.note
        if not n.bend or n.bend_max <= 0:
            continue
        onset = r.onset if r.det is not None else r.expected_onset
        t, p = tracker.note_contour(onset + 0.015, onset + n.duration, n.pitch - 0.8, n.pitch + n.bend_max + 1.0)
        if len(t) < 4:
            continue
        # leere Saite: mit dem Finger nicht zu ziehen, also Tremolo/Whammy – Befunde nur als Hinweis
        open_string = n.fret == 0
        conf = (lambda c: min(c, OPEN_STRING_CONF)) if open_string else (lambda c: c)
        rel = p - n.pitch - tune
        r.contour = [[round(float(a), 3), round(float(b), 2)] for a, b in zip(t[::2], rel[::2])]
        bt = np.array([x for x, _ in n.bend])
        bs = np.array([s for _, s in n.bend])
        exp = np.interp(t - onset, bt, bs)
        target = n.bend_max
        # Gezogen wird oft später als notiert: gesucht wird bis zum Ende des Soll-Plateaus plus Spielraum
        # (bei geschätzten Zeitpunkten über die ganze Note).
        plateau_end = float(bt[bs >= 0.9 * target].max()) if (bs >= 0.9 * target).any() else n.duration
        limit = plateau_end + max(0.3, 0.35 * n.duration) if n.bend_timed else n.duration
        window = (t - onset) <= limit
        reached = float(np.percentile(rel[window] if window.sum() >= 3 else rel, 95))
        dev = (reached - target) * 100
        r.features["bend_reached"] = round(reached, 2)
        amount = msg("semitones", n=f"{target:g}")
        if reached < 0.35 * target:
            issues.add("bend_missing", onset,
                       msg("bend_missing_open" if open_string else "bend_missing", note=note_name(n.pitch), amount=amount),
                       conf(0.75), n, r.det, cents=round(dev))
            continue
        if abs(dev) > tol_cents:
            issues.add("bend_pitch", onset,
                       msg("bend_too_flat" if dev < 0 else "bend_too_sharp", cents=f"{dev:+.0f}",
                           note=note_name(n.pitch), amount=amount),
                       conf(0.5 + min(abs(dev) / 100, 0.4)), n, r.det, cents=round(dev))
        if n.bend_timed:
            expected_peak = float(bt[np.argmax(bs >= 0.9 * target)])
            hit = (t - onset >= 0) & (rel >= 0.9 * reached)
            if hit.any():
                lateness = float((t - onset)[hit][0]) - expected_peak
                if lateness > max(0.25, 0.2 * n.duration):
                    issues.add("bend_late", onset,
                               msg("bend_late", ms=f"{lateness * 1000:.0f}", note=note_name(n.pitch)),
                               conf(0.35), n, r.det, delta_ms=round(lateness * 1000))
        if bs[0] >= 0.5:
            start = rel[t - onset <= 0.05]
            if len(start) and float(np.median(start)) < 0.5 * bs[0]:
                issues.add("prebend_missing", onset,
                           msg("prebend_missing", note=note_name(n.pitch)),
                           conf(0.55), n, r.det)
        if bs[-1] <= 0.1 * target and bs.max() > bs[-1]:
            tail = rel[t >= t[0] + 0.85 * (t[-1] - t[0])]
            if len(tail) and float(np.median(tail)) > 0.4:
                issues.add("release_missing", onset,
                           msg("release_incomplete", cents=f"{float(np.median(tail)) * 100:.0f}"),
                           conf(0.55), n, r.det, cents=round(float(np.median(tail)) * 100))


def evaluate_unwanted(tracker: PitchTracker, results: list[NoteResult], issues: Issues, tuning_cents: float) -> None:
    """Ungewollte Bends/Vibrato bei gehaltenen Einzelnoten ohne entsprechende Vorgabe (niedrige Konfidenz)."""
    tune = tuning_cents / 100
    by_time = sorted(results, key=lambda r: r.note.onset)
    for idx, r in enumerate(by_time):
        n = r.note
        if (r.status != "ok" or r.det is None or r.weak or n.bend or n.slide or n.harmonic or n.dead
                or n.duration < 0.25):
            continue
        if n.vibrato:  # notiertes Vibrato: nur Verlauf für die Anzeige
            t, p = tracker.note_contour(r.onset + 0.03, r.onset + n.duration, n.pitch - 1.0, n.pitch + 1.5)
            r.contour = [[round(float(a), 3), round(float(b - n.pitch - tune), 2)] for a, b in zip(t[::2], p[::2])]
            continue
        neighbours = by_time[max(idx - 8, 0):idx + 8]
        if not _is_single(r, neighbours):
            continue
        t, p = tracker.note_contour(r.onset + 0.03, r.onset + n.duration, n.pitch - 1.0, n.pitch + 1.5)
        if len(p) < 10:
            continue
        rel = p - n.pitch - tune
        sustained = float(np.percentile(rel, 80))
        if sustained > 0.4:
            issues.add("unwanted_bend", r.onset,
                       msg("unwanted_bend", cents=f"{sustained * 100:+.0f}", note=note_name(n.pitch)),
                       0.35, n, r.det, cents=round(sustained * 100))
            continue
        if not n.vibrato and (t[-1] - t[0]) >= 0.3:
            detr = rel - median_filter(rel, size=min(len(rel) // 2 * 2 + 1, 15), mode="nearest")
            crossings = int(np.sum(np.diff(np.sign(rel - np.median(rel))) != 0))
            depth = float(np.percentile(rel, 95) - np.percentile(rel, 5))
            if depth > 0.3 and crossings >= 6 and np.std(detr) < depth:
                issues.add("vibrato_unexpected", r.onset,
                           msg("vibrato_unexpected", cents=f"{depth * 100:.0f}", note=note_name(n.pitch)),
                           0.3, n, r.det, cents=round(depth * 100))
