"""Vorlagengestützte Spektralprüfung von Akkordtönen.

Polyphone Transkription übersieht in dichten Akkorden viele Töne. Hier wird für jeden notierten Akkordton
direkt im Spektrum (CQT, 60 Bins/Oktave) nachgesehen, wie stark seine Grundfrequenz kurz nach dem Anschlag
ist – relativ zum stärksten Teilton des Moments. Kalibriert wird pro Aufnahme: sicher erkannte Töne
zeigen, wie „gespielt“ aussieht, die Halbton-Nachbarn notierter Töne (Griff daneben), wie „nicht gespielt“
aussieht. Töne, deren Grundfrequenz mit einem Oberton eines tieferen klingenden Tons zusammenfällt
(z. B. Oktave über dem Grundton), lassen sich so nicht nachweisen und gelten als nicht prüfbar.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from ..compare import OVERTONES, Issues, NoteResult, note_name
from ..i18n import msg
from ..profile import Chords, PalmMute
from .pitch_contour import BPO, PitchTracker

OMITTED_MAX_CONFIDENCE = 0.3  # systematisch ausgelassene Töne: standardmäßig ausgeblendet, Muster als Warnung
PRESENT_Z = 0.6   # ab hier (0 = typischer Nachbar, 1 = typischer gespielter Ton) gilt ein Ton als vorhanden
ABSENT_Z = 0.2


def salience_db(tracker: PitchTracker, pitch: int, onset: float, duration: float) -> float:
    i0, i1 = np.searchsorted(tracker.times, [onset + 0.03, onset + max(min(0.15, duration), 0.06)])
    b = int(round((pitch - tracker.base) * BPO / 12))
    if i1 <= i0 or b < 2 or b + 3 >= tracker.C.shape[0]:
        return float("nan")
    seg = tracker.C[:, i0:i1]
    value = seg[b - 2:b + 3].max(axis=0).mean()
    ref = seg.max(axis=0).mean()
    return float(20 * np.log10(value / (ref + 1e-12) + 1e-9))


def bar_ranges(bars: set[tuple[int, int]]) -> str:
    """{(8,1), (9,1), (10,1), (13,1), (9,2)} → „8–10, 13, 9 (2.)“ – Takte gruppiert nach Durchgang."""
    parts = []
    for occ in sorted({o for _, o in bars}):
        nums = sorted(b for b, o in bars if o == occ)
        suffix = f" ({occ}.)" if occ > 1 else ""
        start = prev = nums[0]
        for b in nums[1:] + [None]:
            if b is not None and b == prev + 1:
                prev = b
                continue
            parts.append((f"{start}–{prev}" if prev > start else f"{start}") + suffix)
            if b is not None:
                start = prev = b
    return ", ".join(parts)


def _groups(results: list[NoteResult]) -> list[list[NoteResult]]:
    by_onset: dict[float, list[NoteResult]] = defaultdict(list)
    for r in results:
        if not r.note.dead:
            by_onset[round(r.expected_onset, 3)].append(r)
    return [sorted(g, key=lambda r: r.note.pitch) for g in by_onset.values()]


def _masked(r: NoteResult, sounding_pitches: list[int]) -> bool:
    return any(r.note.pitch - q in OVERTONES for q in sounding_pitches if q < r.note.pitch)


def evaluate(tracker: PitchTracker, results: list[NoteResult], issues: Issues, warnings: list[str],
             chords: Chords | None = None, pm: PalmMute | None = None) -> None:
    chords, pm = chords or Chords(), pm or PalmMute()
    groups = [g for g in _groups(results) if len(g) >= 2]
    if not groups:
        return
    pos, neg = [], []
    for g in groups:
        pitches = [r.note.pitch for r in g]
        t = g[0].onset if g[0].det is not None else g[0].expected_onset
        dur = min(r.note.duration for r in g)
        for r in g:
            r.features["salience_db"] = salience_db(tracker, r.note.pitch, t, dur)
            r.features["masked"] = _masked(r, pitches)
            if r.status == "ok" and not r.weak and not r.features["masked"]:
                pos.append(r.features["salience_db"])
            for d in (-1, 1):
                q = r.note.pitch + d
                if q in pitches or any(q - e in OVERTONES or e - q in OVERTONES for e in pitches):
                    continue
                neg.append(salience_db(tracker, q, t, dur))
    pos_a, neg_a = np.array(pos), np.array(neg)
    pos_a, neg_a = pos_a[np.isfinite(pos_a)], neg_a[np.isfinite(neg_a)]
    if len(pos_a) < 20 or len(neg_a) < 20:
        return
    m_pos, m_neg = float(np.median(pos_a)), float(np.median(neg_a))
    if m_pos - m_neg < 3.0:
        warnings.append(msg("chord_check_unavailable"))
        return

    missing_by_key: Counter = Counter()
    total_by_key: Counter = Counter()
    missing_bars: dict[tuple, set] = defaultdict(set)
    pm_quiet: Counter = Counter()
    pm_total: Counter = Counter()
    pm_quiet_bars: dict[int, set] = defaultdict(set)
    for g in groups:
        zs = {}
        for r in g:
            s = r.features.get("salience_db", float("nan"))
            if np.isfinite(s):
                zs[r.note.id] = (s - m_neg) / (m_pos - m_neg)
                r.features["chord_z"] = round(zs[r.note.id], 2)
        # mehrstimmig, wenn mindestens zwei Töne sicher nachgewiesen sind (Transkription oder Spektrum)
        confirmed = sum(1 for r in g if (r.status == "ok" and not r.weak) or zs.get(r.note.id, -1) >= PRESENT_Z)
        polyphonic = confirmed >= 2
        for r in g:
            n = r.note
            if n.id not in zs:
                continue
            z = zs[n.id]
            key = (n.string, n.palm_mute)
            total_by_key[key] += 1
            if r.features["masked"]:
                if r.status == "missing":
                    issues.remove(n.id, {"missing"})
                    r.status = "unchecked"
                continue
            if pm.upper_tones_optional and n.palm_mute and r is not g[0]:
                # Der Handballen dämpft obere Saiten stärker, beim Chug erwischt das Plektrum sie oft gar nicht:
                # obere Töne eines Palm-Mute-Akkords sind optional.
                pm_total[n.string] += 1
                if z < ABSENT_Z:
                    pm_quiet[n.string] += 1
                    pm_quiet_bars[n.string].add((n.bar, n.occurrence))
                if r.status == "missing" or (r.status == "ok" and r.weak and z < ABSENT_Z):
                    issues.remove(n.id, {"missing"})
                    r.status, r.weak = "unchecked", False
                    r.features["uncertain_reason"] = "pm_upper"
                continue
            hard_to_isolate = n.palm_mute or n.pitch < chords.low_pitch
            if r.status == "ok" and r.weak and z < ABSENT_Z:
                r.status, r.weak, r.det = "missing", False, None
                issues.add("missing", r.expected_onset,
                           msg("missing_note_spectral", note=note_name(n.pitch), n=len(g)),
                           0.45, n)
            if r.status == "missing":
                if z >= PRESENT_Z:
                    issues.remove(n.id, {"missing"})
                    r.status, r.weak = "ok", True
                    continue
                if z < ABSENT_Z and n.pitch >= chords.low_pitch:  # tiefe Töne sind für Muster zu unsicher
                    missing_by_key[key] += 1
                    missing_bars[key].add((n.bar, n.occurrence))
                if hard_to_isolate and polyphonic:
                    # Akkord klingt mehrstimmig; einzelner gedämpfter/tiefer Ton nicht sicher isolierbar
                    issues.remove(n.id, {"missing"})
                    r.status = "unchecked"
                    r.features["uncertain_reason"] = "pm_or_low"
                else:
                    cap = chords.uncertain_missing_cap if polyphonic or hard_to_isolate else 0.9
                    issues.set_confidence(n.id, "missing", float(np.clip(0.9 - z, 0.3, cap)))
            elif r.status == "wrong_pitch" and z >= 0.8:
                issues.remove(n.id, {"wrong_pitch"})
                r.status, r.weak, r.played_pitch = "ok", True, None

    for string, count in pm_quiet.items():
        if count >= 10 and count >= 0.3 * pm_total[string]:
            where = msg("where_string", n=string) if string else msg("where_upper_strings")
            nbars, ranges = len(pm_quiet_bars[string]), bar_ranges(pm_quiet_bars[string])
            issues.hints.append(msg("pm_upper_typical", where=where, bars=nbars, count=count, total=pm_total[string], ranges=ranges))

    # Systematische Muster (ohne Palm Mute): als Warnung melden, Einzelmeldungen als „ausgelassen“ herabstufen
    for key, count in missing_by_key.items():
        string, pm = key
        if count < 10 or count < 0.5 * total_by_key[key]:
            continue
        where = msg("where_string", n=string) if string else msg("where_same_position")
        label = msg("label_pm_chords") if pm else ""
        pattern = f"string{string}-pm{int(pm)}"
        nbars, ranges = len(missing_bars[key]), bar_ranges(missing_bars[key])
        warnings.append(msg("chord_tone_pattern", where=where, label=label, bars=nbars, count=count, total=total_by_key[key], ranges=ranges))
        for g in groups:
            for r in g:
                if (r.note.string, r.note.palm_mute) == key and r.status in ("missing", "unchecked") \
                        and r.features.get("chord_z", 1) < ABSENT_Z and not r.features.get("masked"):
                    if r.status == "unchecked":
                        issues.add("chord_tone_omitted", r.expected_onset,
                                   msg("chord_tone_omitted", note=note_name(r.note.pitch)),
                                   OMITTED_MAX_CONFIDENCE, r.note, pattern=pattern)
                    else:
                        issues.retype(r.note.id, "missing", "chord_tone_omitted", OMITTED_MAX_CONFIDENCE,
                                      msg("chord_tone_omitted", note=note_name(r.note.pitch)),
                                      pattern=pattern)
                    r.status = "omitted"
