"""Artikulationsmerkmale pro Note: Anschlag (Pick vs. Legato) und Dämpfung (Palm Mute).

Absolute Schwellen hängen stark von Gitarre, Saiten und Pickup ab. Deshalb werden die Merkmale pro
Aufnahme relativ bewertet: Die Vorlage sagt, welche Noten gedämpft bzw. gebunden sein sollen, und
jede Note wird mit der typischen Ausprägung ihrer Soll-Gruppe in derselben Aufnahme verglichen.
"""

from __future__ import annotations

import numpy as np

from ..compare import Issues, NoteResult, note_name
from ..i18n import tr
from ..profile import PalmMute

HF_BAND = (2500.0, 8000.0)


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _stft(seg: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    if len(seg) < n_fft:
        seg = np.pad(seg, (0, n_fft - len(seg)))
    frames = np.lib.stride_tricks.sliding_window_view(seg, n_fft)[::hop]
    return np.abs(np.fft.rfft(frames * np.hanning(n_fft), axis=1))


def _hf_envelope(y: np.ndarray, sr: int, t0: float, t1: float, n_fft: int = 256, hop: int = 32):
    i0 = max(int(t0 * sr), 0)
    seg = y[i0:int(t1 * sr)]
    if len(seg) < n_fft * 2:
        return np.empty(0), np.empty(0)
    spec = _stft(seg, n_fft, hop) ** 2
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    band = spec[:, (freqs >= HF_BAND[0]) & (freqs <= HF_BAND[1])].sum(axis=1) + 1e-12
    t = i0 / sr + (np.arange(len(band)) * hop + n_fft / 2) / sr
    return t, band


def _strongest_jump(y: np.ndarray, sr: int, t: float, before: float, after: float) -> tuple[float, float]:
    """Zeitpunkt und Höhe (dB) des stärksten Anstiegs der Hochfrequenzenergie in [t − before, t + after]."""
    times, band = _hf_envelope(y, sr, t - before - 0.02, t + after + 0.02)
    if len(band) < 4:
        return t, 0.0
    db = 10 * np.log10(band)
    jump = db[2:] - db[:-2]
    tc = times[1:-1]
    sel = (tc >= t - before) & (tc <= t + after)
    if not sel.any():
        return t, 0.0
    k = int(np.argmax(np.where(sel, jump, -np.inf)))
    return float(tc[k]), float(jump[k])


def refine_onset(y: np.ndarray, sr: int, onset: float, min_jump_db: float = 6.0) -> float:
    """Onset auf den Pick-Anschlag nachschärfen (stärkster Anstieg der Hochfrequenzenergie).

    Basic Pitch liegt bei Onsets oft 10–20 ms daneben; das verfälscht Timing und Anschlagsmessung.
    Ohne deutlichen Anstieg (z. B. Legato) bleibt der ursprüngliche Onset.
    """
    t, jump = _strongest_jump(y, sr, onset, before=0.04, after=0.03)
    return t if jump >= min_jump_db else onset


def has_attack(y: np.ndarray, sr: int, t: float, window: float = 0.02, min_jump_db: float = 6.0) -> bool:
    """Gibt es um `t` einen hörbaren Anschlag?"""
    return _strongest_jump(y, sr, t, before=window, after=window)[1] >= min_jump_db


def attack_db(y: np.ndarray, sr: int, onset: float) -> float:
    """Hochfrequente Energie (Pick-Geräusch) direkt nach dem Onset relativ zu davor, in dB."""
    t, band = _hf_envelope(y, sr, onset - 0.06, onset + 0.04)
    if not len(band):
        return float("nan")
    pre = band[(t >= onset - 0.05) & (t <= onset - 0.01)]
    post = band[(t >= onset - 0.005) & (t <= onset + 0.03)]
    if not len(pre) or not len(post):
        return float("nan")
    return float(10 * np.log10(post.max() / np.median(pre)))


def decay_features(y: np.ndarray, sr: int, onset: float, window: float, pitch: int) -> dict:
    """Abklingrate (dB/s) und Helligkeit (Obertöne 3–8 vs. 1–2) der Teiltöne der Note."""
    out = {"decay_db_s": float("nan"), "brightness_db": float("nan")}
    if window < 0.06:
        return out
    n_fft, hop = 1024, 64
    i0 = max(int(onset * sr), 0)
    seg = y[i0:int((onset + window) * sr)]  # Frames enden innerhalb des Fensters (nicht in der nächsten Note)
    if len(seg) < n_fft + 3 * hop:
        return out
    spec = _stft(seg, n_fft, hop)
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    f0 = _hz(pitch)
    partials = []
    for k in range(1, 9):
        b = int(round(k * f0 / (freqs[1])))
        if b + 1 >= spec.shape[1]:
            break
        partials.append(spec[:, max(b - 1, 0):b + 2].max(axis=1))
    if len(partials) < 3:
        return out
    P = np.array(partials)                # (Teiltöne, Frames)
    env = 20 * np.log10(P[:6].sum(axis=0) + 1e-9)
    peak = int(np.argmax(env[:max(int(0.03 * sr / hop), 1)]))
    tail = env[peak:]
    if len(tail) >= 3:
        t = np.arange(len(tail)) * hop / sr
        out["decay_db_s"] = float(np.polyfit(t, tail, 1)[0])
    frame = min(peak + 2, P.shape[1] - 1)
    low = (P[:2, frame] ** 2).sum() + 1e-12
    high = (P[2:, frame] ** 2).sum() + 1e-12
    out["brightness_db"] = float(10 * np.log10(high / low))
    return out


def _robust(values: list[float]) -> tuple[float, float]:
    v = np.array([x for x in values if np.isfinite(x)])
    if not len(v):
        return float("nan"), float("nan")
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med))) * 1.4826
    return med, max(mad, 1e-6)


def evaluate(results: list[NoteResult], issues: Issues, warnings: list[str], cfg: PalmMute | None = None) -> None:
    cfg = cfg or PalmMute()
    candidates = [r for r in results if r.status == "ok" and r.det is not None and not r.weak
                  and not r.note.dead and not r.note.harmonic and not r.note.bend]
    _evaluate_palm_mute(results, candidates, issues, warnings, cfg)
    _evaluate_legato(candidates, issues)


def _events(results: list[NoteResult]) -> list[list[NoteResult]]:
    by_onset: dict[float, list[NoteResult]] = {}
    for r in results:
        if not r.note.dead:
            by_onset.setdefault(round(r.note.onset, 3), []).append(r)
    return [sorted(by_onset[k], key=lambda r: r.note.pitch) for k in sorted(by_onset)]


def _lift_points(events: list[list[NoteResult]]) -> set[int]:
    """Stellen, an denen Gitarristen den Handballen typischerweise kurz anheben: Taktanfang, erster Ton nach
    einer Pause, Beginn eines Palm-Mute-Laufs, Wechsel des Griffs. Liefert die IDs der tiefsten Töne."""
    out = set()
    for k, ev in enumerate(events):
        root = ev[0].note
        if k == 0:
            out.add(root.id)
            continue
        prev = events[k - 1]
        prev_end = max(r.note.end for r in prev)
        rest_before = root.onset - prev_end > 0.05
        run_start = not prev[0].note.palm_mute
        grip_change = {r.note.pitch for r in ev} != {r.note.pitch for r in prev}
        if root.beat == 1 or rest_before or run_start or grip_change:
            out.add(root.id)
    return out


def _evaluate_palm_mute(results: list[NoteResult], rs: list[NoteResult], issues: Issues, warnings: list[str],
                        cfg: PalmMute) -> None:
    # Der Handballen liegt vor allem auf den tiefen Saiten: geprüft wird nur der tiefste Ton jedes Anschlags.
    events = _events(results)
    lift = _lift_points(events) if cfg.lift_points else set()
    if cfg.root_only:
        roots = {ev[0].note.id for ev in events}
        rs = [r for r in rs if r.note.id in roots]
    pm = [r for r in rs if r.note.palm_mute and not r.note.legato]
    open_ = [r for r in rs if not r.note.palm_mute and not r.note.legato]
    if len(pm) < 4 or len(open_) < 4:
        return
    scales = []
    for feat in ("decay_db_s", "brightness_db"):
        m_pm, s_pm = _robust([r.features.get(feat, np.nan) for r in pm])
        m_op, s_op = _robust([r.features.get(feat, np.nan) for r in open_])
        if not (np.isfinite(m_pm) and np.isfinite(m_op)):
            continue
        separation = (m_op - m_pm) / np.hypot(s_pm, s_op)
        if separation > 0.8:  # offene Noten klingen länger/heller als gedämpfte
            scales.append((feat, m_pm, m_op))
    if not scales:
        warnings.append(tr("Palm Mutes und offene Noten klingen in dieser Aufnahme kaum unterschiedlich – "
                           "möglicherweise wurde durchgehend gedämpft oder gar nicht gedämpft. "
                           "Palm-Mute-Prüfung pro Note übersprungen.",
                           "Palm-muted and open notes sound almost the same in this take – possibly everything "
                           "was muted or nothing was. Per-note palm mute check skipped."))
        return
    per_feature: dict[int, list[float]] = {}
    for r in pm + open_:
        vals = []
        for feat, m_pm, m_op in scales:
            v = r.features.get(feat, np.nan)
            if np.isfinite(v):
                vals.append((v - m_pm) / (m_op - m_pm))  # 0 = typisch gedämpft, 1 = typisch offen
        if vals:
            per_feature[r.note.id] = vals
            r.features["openness"] = round(float(np.mean(vals)), 2)
    pm_times = np.array([r.note.onset for r in pm if r.note.id in per_feature])
    pm_open = np.array([r.features["openness"] for r in pm if r.note.id in per_feature])

    for r in pm + open_:
        vals = per_feature.get(r.note.id)
        if not vals:
            continue
        n = r.note
        openness = float(np.mean(vals))
        # Vorsichtig: Alle gemessenen Merkmale müssen übereinstimmen. Ein einzelnes Merkmal kann z. B. durch
        # den nächsten Anschlag im Messfenster verfälscht sein (flaches Abklingen bei dunklem Klang).
        both = len(vals) >= 2
        clearly_open = min(vals) > 0.6 and openness > 0.75 if both else openness > 1.0
        clearly_muted = max(vals) < 0.4 and openness < 0.25 if both else openness < 0.0
        factor = 1.0 if both else 0.8
        if n.palm_mute and clearly_open:
            # Dämpfungsstärke schwankt im Riff: nur Ausreißer gegenüber den gedämpften Noten der Umgebung
            near = np.abs(pm_times - n.onset) <= cfg.local_window_s
            local = float(np.median(pm_open[near])) if near.sum() >= 4 else 0.0
            if openness - local < cfg.outlier_margin:
                continue
            msg = tr(f"Palm Mute fehlt: {note_name(n.pitch)} klingt offen",
                     f"Palm mute missing: {note_name(n.pitch)} rings open")
            if n.id in lift:
                factor *= cfg.lift_confidence_factor
                msg += tr(" (Taktanfang/Wechsel – hier wird der Handballen oft kurz angehoben)",
                          " (downbeat/change – players often lift the palm briefly here)")
            issues.add("pm_missing", r.onset, msg, (0.4 + 0.4 * min(openness - 0.75, 1.0)) * factor, n, r.det)
        elif not n.palm_mute and clearly_muted:
            issues.add("pm_unexpected", r.onset,
                       tr(f"Gedämpft gespielt, aber kein Palm Mute notiert: {note_name(n.pitch)}",
                          f"Played muted, but no palm mute notated: {note_name(n.pitch)}"),
                       (0.3 + 0.3 * min(0.25 - openness, 1.0)) * factor, n, r.det)


def _evaluate_legato(rs: list[NoteResult], issues: Issues) -> None:
    picked = [r for r in rs if not r.note.legato]
    legato = [r for r in rs if r.note.legato]
    att = [r.features.get("attack_db", np.nan) for r in picked]
    med, mad = _robust(att)
    if not np.isfinite(med) or len(picked) < 6:
        return
    q25 = float(np.nanpercentile(att, 25))
    for r in legato:
        a = r.features.get("attack_db", np.nan)
        if np.isfinite(a) and a > q25 and a > 3.0:
            issues.add("legato_picked", r.onset,
                       tr(f"Angeschlagen statt Legato (Hammer-on/Pull-off): {note_name(r.note.pitch)}",
                          f"Picked instead of legato (hammer-on/pull-off): {note_name(r.note.pitch)}"),
                       0.4 + 0.4 * min((a - q25) / (2 * mad), 1.0), r.note, r.det)
    onsets: dict[float, int] = {}
    for r in picked:
        onsets[round(r.note.onset, 3)] = onsets.get(round(r.note.onset, 3), 0) + 1
    for r in picked:
        a = r.features.get("attack_db", np.nan)
        single = onsets[round(r.note.onset, 3)] == 1
        if single and np.isfinite(a) and a < med - 3 * mad and a < 3.0:
            issues.add("picked_legato", r.onset,
                       tr(f"Kein Anschlag hörbar (gebunden statt angeschlagen?): {note_name(r.note.pitch)}",
                          f"No pick attack audible (legato instead of picked?): {note_name(r.note.pitch)}"),
                       0.35, r.note, r.det)
