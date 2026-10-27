"""Gesamte Analyse: Vorlage + Aufnahme → Ergebnis-Dictionary (JSON-fähig)."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import numpy as np

from .audio import articulation, chord_check, harmonics, pitch_contour, stops, strum
from .audio.align import estimate_offset
from .audio.transcribe import Transcription, transcribe
from .compare import Issues, NoteResult, Options, match_notes, timing_issues
from .i18n import msg, to_json
from .profile import Profile, load_profile
from .score import Score, load_score

SR = 22050
# Sicherheitsstufen für die Übersicht: sicher / wahrscheinlich (Standardansicht ab 0,5) / unsicher
TIER_HIGH, TIER_MEDIUM = 0.7, 0.5


def issue_tiers(issues: list[dict]) -> dict[str, int]:
    tiers = {"high": 0, "medium": 0, "low": 0}
    for i in issues:
        c = i["confidence"]
        tiers["high" if c >= TIER_HIGH else "medium" if c >= TIER_MEDIUM else "low"] += 1
    return tiers


RESULT_VERSION = 3  # erhöhen, wenn neue Prüfungen/Felder dazukommen – ältere Analysen werden als veraltet markiert
# Transkription immer im vollen Bereich (bis 9-Saiter/Flageoletts), damit der Cache bei geänderter
# Stimmung gültig bleibt; gefiltert wird danach auf den Bereich der Vorlage.
TRANSCRIBE_RANGE = (24, 108)
Progress = Callable[[str, float], None]


def _noop(stage: str, fraction: float) -> None:
    pass


def load_audio(path: str | Path) -> np.ndarray:
    import librosa
    y, _ = librosa.load(str(path), sr=SR, mono=True)
    return y


def waveform_peaks(y: np.ndarray, per_second: int = 100) -> list[list[float]]:
    hop = SR // per_second
    n = len(y) // hop
    frames = y[:n * hop].reshape(n, hop)
    return np.round(np.stack([frames.min(axis=1), frames.max(axis=1)], axis=1), 3).tolist()


def pitch_range(score: Score) -> tuple[int, int]:
    """Erkennungsbereich: tiefste Saite (bzw. tiefste Note) bis höchste erwartete Tonhöhe inkl. Bends."""
    lows = [n.pitch for n in score.notes] + ([min(score.tuning)] if score.tuning else [])
    highs = [n.pitch + int(np.ceil(n.bend_max)) for n in score.notes] + [p for n in score.notes for p in n.alt_pitches]
    lo = min(lows, default=40) - 2
    hi = max(highs, default=88) + 3
    return max(lo, 21), min(hi, 108)


def _note_windows(score: Score) -> dict[int, float]:
    """Messfenster für Abklingmerkmale: bis zur nächsten Note auf derselben Saite (bzw. nächstem Anschlag)."""
    notes = sorted(score.notes, key=lambda n: n.onset)
    onsets = sorted({round(n.onset, 4) for n in notes})
    windows = {}
    for i, n in enumerate(notes):
        nxt = None
        for m in notes[i + 1:]:
            if m.onset <= n.onset + 1e-4:
                continue
            if n.string is None or m.string == n.string:
                nxt = m.onset
                break
            if m.onset > n.onset + 0.4:
                break
        if nxt is None and n.string is None:
            later = [o for o in onsets if o > n.onset + 1e-4]
            nxt = later[0] if later else None
        end = min(n.end, nxt) if nxt is not None else n.end
        windows[n.id] = min(end - n.onset, 0.4)
    return windows


def analyze(score_path: str | Path, audio_path: str | Path, opts: Options | None = None,
            tuning: list[int] | None = None, offset: float | None = None,
            cache_dir: Path | None = None, progress: Progress = _noop, profile: str | Profile | None = None) -> dict:
    profile = profile if isinstance(profile, Profile) else load_profile(profile)
    if opts is None:
        opts = Options(timing_tol=profile.timing.tolerance_ms / 1000)
    opts.bend_tol_cents = profile.bends.tolerance_cents
    t_start = time.time()
    progress("read_score", 0.02)
    score = load_score(score_path, tuning)
    warnings = list(score.warnings)
    if not score.notes:
        raise ValueError("Die Vorlage enthält keine Noten.")

    progress("load_audio", 0.05)
    y = load_audio(audio_path)
    lo, hi = pitch_range(score)

    cache = cache_dir / "transcription.npz" if cache_dir else None
    if cache is not None and cache.exists():
        trans = Transcription.load(cache)
    else:
        progress("transcribe", 0.1)
        trans = transcribe(audio_path, min_pitch=TRANSCRIBE_RANGE[0], max_pitch=TRANSCRIBE_RANGE[1])
        if cache is not None:
            trans.save(cache)
    trans.notes = [d for d in trans.notes if lo <= d.pitch <= hi]

    progress("align", 0.45)
    manual_offset = offset is not None
    if offset is None:
        offset, quality = estimate_offset(score.notes, trans.notes)
        if quality < 0.3:
            warnings.append(msg("alignment_uncertain", percent=f"{quality:.0%}"))

    progress("compare", 0.5)
    refine = lambda t: articulation.refine_onset(y, SR, t)  # noqa: E731
    has_attack = lambda t: articulation.has_attack(y, SR, t)  # noqa: E731
    issues = Issues(score, offset)
    results, _ = match_notes(score, trans, offset, opts, issues, refine=refine, has_attack=has_attack, timing=False)
    if not manual_offset:
        # Basic-Pitch-Onsets liegen meist etwas hinter dem Pick-Anschlag; den Versatz daher an den
        # nachgeschärften Onsets ausrichten, damit Timing-Abweichungen um null streuen.
        deltas = [r.delta for r in results if r.status == "ok" and not r.weak and r.played_onset is not None
                  and r.played_onset != r.det.onset]
        if len(deltas) >= 10 and abs(float(np.median(deltas))) > 0.003:
            offset = round(offset + float(np.median(deltas)), 4)
            issues = Issues(score, offset)
            results, _ = match_notes(score, trans, offset, opts, issues, refine=refine, has_attack=has_attack,
                                     timing=False)
    strum.evaluate(results, trans, issues, profile.strum)
    timing_issues(results, opts, issues, profile)

    progress("articulation", 0.6)
    windows = _note_windows(score)
    for r in results:
        if r.status == "ok" and r.det is not None and not r.weak and not r.note.dead:
            r.features["attack_db"] = articulation.attack_db(y, SR, r.onset)
            r.features.update(articulation.decay_features(y, SR, r.onset, windows[r.note.id], r.note.pitch))
    articulation.evaluate(results, issues, warnings, profile.palm_mute)

    progress("pitch", 0.7)
    tracker = pitch_contour.PitchTracker(y, SR, lo)
    tuning_cents = pitch_contour.estimate_tuning(tracker, results)
    if tuning_cents is not None and abs(tuning_cents) >= 15:
        warnings.append(msg("tuning_sharp" if tuning_cents > 0 else "tuning_flat", cents=f"{tuning_cents:+.0f}"))
    pitch_contour.evaluate_bends(tracker, results, issues, tuning_cents or 0.0, opts.bend_tol_cents)
    pitch_contour.evaluate_unwanted(tracker, results, issues, tuning_cents or 0.0)

    progress("chords", 0.8)
    chord_check.evaluate(tracker, results, issues, warnings, profile.chords, profile.palm_mute)

    progress("stops", 0.85)
    stops.evaluate(y, SR, tracker, score.notes, results, offset, issues, warnings, profile.stops)
    issues.renumber()

    progress("harmonics", 0.9)
    harmonics.evaluate(tracker, results, issues)

    progress("result", 0.95)
    result = build_result(score, trans, results, issues, offset, tuning_cents, len(y) / SR, warnings, opts)
    result["profile"] = {"id": profile.id, "name": profile.name}
    result["score_track"] = score.track_index
    result["version"] = RESULT_VERSION
    result["display"] = {"strum_direction": profile.strum.show_direction}
    result["meta"] = {"analysis_seconds": round(time.time() - t_start, 1), "pitch_range": [lo, hi]}
    return result


def _clean(features: dict) -> dict:
    return {k: (None if isinstance(v, float) and not np.isfinite(v) else round(v, 2) if isinstance(v, float) else v)
            for k, v in features.items()}


def build_result(score: Score, trans: Transcription, results: list[NoteResult], issues: Issues, offset: float,
                 tuning_cents: float | None, duration: float, warnings: list[str], opts: Options) -> dict:
    issue_by_note: dict[int, list[str]] = {}
    for it in issues.items:
        if it["note_id"] is not None:
            issue_by_note.setdefault(it["note_id"], []).append(it["type"])
    notes = []
    for r in results:
        n = r.note
        notes.append({
            "id": n.id, "onset": round(r.expected_onset, 4), "duration": round(n.duration, 4), "pitch": n.pitch,
            "bar": n.bar, "occurrence": n.occurrence, "beat": n.beat, "string": n.string, "fret": n.fret,
            "palm_mute": n.palm_mute, "legato": n.legato, "slide": n.slide, "vibrato": n.vibrato, "dead": n.dead,
            "harmonic": n.harmonic, "fretted_pitch": n.fretted_pitch,
            "bend": None if not n.bend else [[round(t, 3), round(s, 2)] for t, s in n.bend],
            "status": r.status, "weak": r.weak, "evidence": round(r.evidence, 2),
            "det_id": None if r.det is None else r.det.id,
            "delta_ms": None if r.delta is None else round(r.delta * 1000, 1),
            "played_pitch": r.played_pitch, "issues": issue_by_note.get(n.id, []),
            "strum": r.strum, "chord_lead": r.chord_lead,
            "chord_delta_ms": None if r.chord_delta is None else round(r.chord_delta * 1000, 1),
            "groove_ms": None if r.groove is None else round(r.groove * 1000, 1),
            "features": _clean(r.features), "contour": r.contour,
        })
    used = {r.det.id for r in results if r.det is not None}
    detected = [{"id": d.id, "onset": round(d.onset, 4), "duration": round(d.duration, 4), "pitch": d.pitch,
                 "amplitude": round(d.amplitude, 3), "matched": d.id in used} for d in trans.notes]
    bars = [{"number": b.number, "occurrence": b.occurrence, "start": round(b.start + offset, 4),
             "end": round(b.end + offset, 4), "beats": b.beats, "beat_type": b.beat_type} for b in score.bars]
    counts = Counter(it["type"] for it in issues.items)
    checked = [r for r in results if r.status not in ("dead", "unchecked")]
    return {
        "title": score.title, "offset": offset, "duration": round(duration, 3),
        "tuning": score.tuning, "tuning_cents": tuning_cents,
        "options": asdict(opts), "warnings": [to_json(w) for w in warnings],
        "hints": [to_json(h) for h in issues.hints],
        "summary": {
            "notes_total": len(results), "notes_checked": len(checked),
            "notes_ok": sum(1 for r in checked if r.status == "ok" and not issue_by_note.get(r.note.id)),
            "issue_counts": dict(counts),
            "issue_tiers": issue_tiers(issues.items),
        },
        "bars": bars, "notes": notes, "detected": detected, "issues": issues.items,
    }
