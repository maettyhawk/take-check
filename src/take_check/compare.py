"""Zuordnung Vorlage ↔ erkannte Noten und Einordnung der Abweichungen."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import numpy as np
from scipy.optimize import linear_sum_assignment

from .audio.transcribe import DetectedNote, Transcription
from .i18n import T, as_text, tr
from .score.guitar import PINCH_INTERVALS
from .score.model import Score, ScoreNote

if TYPE_CHECKING:
    from .profile import Profile

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
OVERTONES = (12, 19, 24, 28, 31)  # Halbtonabstände der Teiltöne 2–6


def note_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


@dataclass
class Options:
    timing_tol: float = 0.030      # s, ab hier zu früh/zu spät
    match_window: float = 0.120    # s, maximale Onset-Abweichung für eine Zuordnung
    min_match_window: float = 0.035  # s, Untergrenze bei schnellen Passagen
    evidence_threshold: float = 0.35  # Posteriorgramm-Schwelle der vorlagengestützten Prüfung
    bend_tol_cents: float = 30.0


@dataclass
class NoteResult:
    note: ScoreNote
    expected_onset: float                 # Audiozeit
    status: str = "missing"               # ok | missing | wrong_pitch | dead | unchecked | omitted
    det: DetectedNote | None = None
    weak: bool = False                    # nur über das Posteriorgramm bestätigt
    evidence: float = 0.0
    played_pitch: int | None = None
    features: dict = field(default_factory=dict)
    contour: list | None = None
    played_onset: float | None = None     # nachgeschärfter Onset (sonst der von Basic Pitch)
    strum: dict | None = None             # Akkorde: Anschlagsrichtung/-dauer (gemeinsam für alle Töne)
    chord_lead: bool = False              # Akkordton, an dem das Akkord-Timing hängt (zuerst angeschlagen)
    chord_delta: float | None = None      # Akkord-Timing: erster Anschlag − notierte Zeit
    groove: float | None = None           # lokaler Groove des Spielers an dieser Stelle (s, + = hinter dem Klick)

    @property
    def onset(self) -> float | None:
        if self.played_onset is not None:
            return self.played_onset
        return None if self.det is None else self.det.onset

    @property
    def delta(self) -> float | None:
        return None if self.det is None else self.onset - self.expected_onset


class Issues:
    def __init__(self, score: Score, offset: float):
        self.score = score
        self.offset = offset
        self.items: list[dict] = []
        self.hints: list[T] = []  # neutrale Einordnungen („typisch für …“), keine Fehler

    def add(self, type_: str, time: float, message: T | str, confidence: float, note: ScoreNote | None = None,
            det: DetectedNote | None = None, **extra) -> None:
        bar, occ, beat = self.score.bar_at(time - self.offset)
        if note is not None:
            bar, occ, beat = note.bar, note.occurrence, note.beat
        self.items.append({
            "id": len(self.items), "type": type_, "time": round(time, 4), "bar": bar, "occurrence": occ,
            "beat": beat, "note_id": None if note is None else note.id, "det_id": None if det is None else det.id,
            "pitch": None if note is None else note.pitch, "confidence": round(float(np.clip(confidence, 0, 1)), 2),
            "message": str(message), "messages": as_text(message), **extra,
        })

    def remove(self, note_id: int, types: set[str]) -> None:
        self.items = [i for i in self.items if not (i["note_id"] == note_id and i["type"] in types)]

    def set_confidence(self, note_id: int, type_: str, confidence: float) -> None:
        for i in self.items:
            if i["note_id"] == note_id and i["type"] == type_:
                i["confidence"] = round(float(np.clip(confidence, 0, 1)), 2)

    def scale_confidence(self, note_id: int, type_: str, factor: float, **extra) -> None:
        for i in self.items:
            if i["note_id"] == note_id and i["type"] == type_:
                i["confidence"] = round(i["confidence"] * factor, 2)
                i.update(extra)

    def retype(self, note_id: int, old_type: str, new_type: str, max_confidence: float, message: T | str, **extra) -> None:
        for i in self.items:
            if i["note_id"] == note_id and i["type"] == old_type:
                i.update(type=new_type, confidence=min(i["confidence"], max_confidence), message=str(message),
                         messages=as_text(message), **extra)

    def renumber(self) -> None:
        for k, i in enumerate(self.items):
            i["id"] = k


class _TimeIndex:
    """Erkannte Noten nach Onset sortiert, für schnelle Fensterabfragen."""

    def __init__(self, detected: list[DetectedNote]):
        self.notes = sorted(detected, key=lambda d: d.onset)
        self.onsets = [d.onset for d in self.notes]

    def window(self, t0: float, t1: float) -> list[DetectedNote]:
        return self.notes[bisect_left(self.onsets, t0):bisect_right(self.onsets, t1)]


def _match_windows(notes: list[ScoreNote], opts: Options) -> dict[int, float]:
    """Zuordnungsfenster pro Note: höchstens halber Abstand zum nächsten notierten Anschlag.

    Sonst kann bei schnellen Chugs (z. B. 32tel mit 117 ms Abstand) eine erkannte Note dem Nachbarschlag
    zugeordnet werden und erscheint als grober Timingfehler.
    """
    onsets = sorted({round(n.onset, 4) for n in notes})
    out = {}
    for n in notes:
        k = bisect_left(onsets, round(n.onset, 4))
        gaps = [onsets[k] - onsets[k - 1]] if k > 0 else []
        if k + 1 < len(onsets):
            gaps.append(onsets[k + 1] - onsets[k])
        limit = 0.5 * min(gaps) if gaps else opts.match_window
        out[n.id] = float(np.clip(limit, opts.min_match_window, opts.match_window))
    return out


def _chord_size(notes: list[ScoreNote]) -> dict[int, int]:
    by_onset: dict[float, int] = defaultdict(int)
    for n in notes:
        by_onset[round(n.onset, 3)] += 1
    return {n.id: by_onset[round(n.onset, 3)] for n in notes}


def match_notes(score: Score, trans: Transcription, offset: float, opts: Options, issues: Issues,
                refine: Callable[[float], float] | None = None,
                has_attack: Callable[[float], bool] | None = None,
                timing: bool = True) -> tuple[list[NoteResult], set[int]]:
    results = {n.id: NoteResult(n, n.onset + offset) for n in score.notes}
    win = _match_windows(score.notes, opts)
    detected = trans.notes
    index = _TimeIndex(detected)
    used: set[int] = set()
    absorbed: set[int] = _fragments(detected, has_attack)

    # Dead Notes: keine Tonhöhe prüfbar; erkannte Noten rund um den Anschlag gehören dazu
    for r in results.values():
        if r.note.dead:
            r.status = "dead"
            for d in index.window(r.expected_onset - 0.06, r.expected_onset + 0.06):
                if d.duration < 0.25:
                    absorbed.add(d.id)

    # 1. Durchgang: exakte Tonhöhe, pro Tonhöhe optimale Zuordnung nach Onset-Abstand
    score_by_pitch: dict[int, list[NoteResult]] = defaultdict(list)
    det_by_pitch: dict[int, list[DetectedNote]] = defaultdict(list)
    for r in results.values():
        if r.status != "dead":
            score_by_pitch[r.note.pitch].append(r)
    for d in detected:
        det_by_pitch[d.pitch].append(d)
    for pitch, rs in score_by_pitch.items():
        ds = [d for d in det_by_pitch.get(pitch, []) if d.id not in absorbed]
        if not ds:
            continue
        exp = np.array([r.expected_onset for r in rs])
        ons = np.array([d.onset for d in ds])
        cost = np.abs(exp[:, None] - ons[None, :])
        big = 1e6
        limits = np.array([win[r.note.id] for r in rs])
        cost = np.where(cost <= limits[:, None], cost, big)
        rows, cols = linear_sum_assignment(cost)
        for i, j in zip(rows, cols):
            if cost[i, j] < big:
                rs[i].det, rs[i].status = ds[j], "ok"
                used.add(ds[j].id)

    # 2. Durchgang: alternative Tonhöhen (Pinch-/künstliche Flageoletts), Oktavfehler bei Flageoletts
    for r in results.values():
        if r.status != "missing":
            continue
        alts = set(r.note.alt_pitches)
        if r.note.harmonic:  # Oktavfehler der Erkennung bei obertonarmen Flageoletts tolerieren
            alts |= {r.note.pitch + 12, r.note.pitch - 12}
            alts.discard(r.note.fretted_pitch)
        best = _nearest_unused(index, used | absorbed, r.expected_onset, win[r.note.id], alts)
        if best is not None:
            r.det, r.status = best, "ok"
            used.add(best.id)

    # Bends: erkannte Noten im Bend-Bereich während der Note gehören zum Bend
    for r in results.values():
        if r.note.bend and r.note.bend_max > 0:
            hi = r.note.pitch + int(np.ceil(r.note.bend_max))
            for d in index.window(r.expected_onset - 0.03, r.expected_onset + r.note.duration):
                if d.id in used or d.id in absorbed:
                    continue
                if r.note.pitch <= d.pitch <= hi:
                    if r.status == "missing" and abs(d.onset - r.expected_onset) <= win[r.note.id]:
                        r.det, r.status = d, "ok"  # z. B. Pre-Bend: erkannt wird der Zielton
                        used.add(d.id)
                    else:
                        absorbed.add(d.id)

    # 3. Nicht zugeordnete Vorlagennoten: Posteriorgramm prüfen, sonst falscher Ton oder fehlend
    chord = _chord_size(score.notes)
    by_onset = sorted(results.values(), key=lambda r: r.expected_onset)
    onsets = [r.expected_onset for r in by_onset]
    max_dur = max((r.note.duration for r in by_onset), default=0.0)

    def overtone_pitches(t: float) -> set[int]:
        """Obertöne der laut Vorlage gerade klingenden Töne – keine Kandidaten für „falscher Ton“."""
        lo, hi = bisect_left(onsets, t - max_dur - 0.05), bisect_right(onsets, t + 0.05)
        return {o.note.pitch + i for o in by_onset[lo:hi] if o.expected_onset + o.note.duration >= t - 0.05
                for i in OVERTONES}

    for r in sorted(results.values(), key=lambda r: r.expected_onset):
        if r.status != "missing":
            continue
        t = r.expected_onset
        r.evidence = trans.evidence(r.note.pitch, t - 0.05, t + 0.12)
        # Aktivierung kann vom Oberton eines tieferen, nicht zugeordneten Tons stammen
        overtone_source = _nearest_unused(index, used | absorbed, t, win[r.note.id],
                                          {r.note.pitch - i for i in (12, 19, 24)})
        if r.evidence >= opts.evidence_threshold and overtone_source is None:
            r.status, r.weak = "ok", True
            continue
        cand = _nearest_unused(index, used | absorbed, t, win[r.note.id], None,
                               exclude_pitches={r.note.pitch} | overtone_pitches(t), near_pitch=r.note.pitch)
        n = r.note
        if cand is not None:
            used.add(cand.id)
            r.det, r.status, r.played_pitch = cand, "wrong_pitch", cand.pitch
            if n.harmonic and cand.pitch == n.fretted_pitch:
                label = (tr("Pinch-Harmonic nicht gelungen", "Pinch harmonic didn't sound") if n.harmonic == "pinch"
                         else tr("Gegriffen statt Flageolett", "Fretted instead of harmonic"))
                issues.add("harmonic_fretted", cand.onset,
                           label + tr(f": {note_name(cand.pitch)} statt {note_name(n.pitch)} (Flageolett)",
                                      f": {note_name(cand.pitch)} instead of {note_name(n.pitch)} (harmonic)"),
                           0.55 if n.harmonic == "pinch" else 0.8, n, cand, played_pitch=cand.pitch)
                continue
            hint = ""
            if cand.pitch - n.pitch in PINCH_INTERVALS:
                hint = tr(" – evtl. ungewolltes Flageolett/Pinch", " – possibly an unintended harmonic/pinch")
            elif abs(cand.pitch - n.pitch) == 12:
                hint = tr(" – Oktave daneben (kann auch ein Erkennungsfehler sein)",
                          " – off by an octave (may also be a detection error)")
            conf = 0.5 + 0.4 * min(cand.amplitude / 0.5, 1.0)
            if abs(cand.pitch - n.pitch) == 12:
                conf *= 0.6
            issues.add("wrong_pitch", cand.onset,
                       tr(f"Falscher Ton: {note_name(cand.pitch)} statt {note_name(n.pitch)}",
                          f"Wrong note: {note_name(cand.pitch)} instead of {note_name(n.pitch)}") + hint,
                       conf, n, cand, played_pitch=cand.pitch)
        else:
            conf = (1 - r.evidence / opts.evidence_threshold) * (0.75 if chord[n.id] >= 3 else 1.0)
            issues.add("missing", t, tr(f"Fehlende Note: {note_name(n.pitch)}", f"Missing note: {note_name(n.pitch)}")
                       + (tr(f" (Akkord mit {chord[n.id]} Tönen)", f" (chord of {chord[n.id]} notes)")
                          if chord[n.id] > 1 else ""),
                       max(conf, 0.3), n)

    ordered = sorted(results.values(), key=lambda r: (r.expected_onset, r.note.pitch))
    if refine is not None:
        for r in ordered:
            if r.det is not None and not r.weak:
                r.played_onset = refine(r.det.onset)
    if timing:
        timing_issues(ordered, opts, issues)
    _extra_notes(ordered, index, used | absorbed, issues, has_attack)
    return ordered, used


def _nearest_unused(index: _TimeIndex, taken: set[int], t: float, window: float,
                    pitches: set[int] | None, exclude_pitches: set[int] | None = None,
                    near_pitch: int | None = None) -> DetectedNote | None:
    """Nächstliegende freie erkannte Note; mit `near_pitch` zählt auch der Tonhöhenabstand (8 ms je Halbton)."""
    best, best_cost = None, float("inf")
    for d in index.window(t - window, t + window):
        if d.id in taken or (pitches is not None and d.pitch not in pitches):
            continue
        if exclude_pitches and d.pitch in exclude_pitches:
            continue
        cost = abs(d.onset - t) + (0.008 * abs(d.pitch - near_pitch) if near_pitch is not None else 0.0)
        if cost < best_cost:
            best, best_cost = d, cost
    return best


def _fragments(detected: list[DetectedNote], has_attack: Callable[[float], bool] | None = None) -> set[int]:
    """Vorläufer eines direkt anschließenden Tons gleicher Tonhöhe, die keine eigene Note sind.

    Basic Pitch erzeugt diese besonders bei tiefen Tönen bis zu einige 100 ms vor dem eigentlichen Anschlag,
    teils als Kette mehrerer Stücke. Mit Audiozugriff (`has_attack`) gilt ein Vorläufer ohne eigenen
    Pick-Anschlag vor einem Ton mit Anschlag als Fragment. Ohne Audio entscheidet die Lautstärke
    (kurz und deutlich leiser); gleich laute Wiederholungen wie Chugs bleiben dann erhalten.
    """
    by_pitch: dict[int, list[DetectedNote]] = defaultdict(list)
    for d in detected:
        by_pitch[d.pitch].append(d)
    out = set()
    for ds in by_pitch.values():
        ds.sort(key=lambda d: d.onset)
        head = ds[-1] if ds else None  # eigentlicher Ton am Ende einer Fragmentkette
        head_attack = None
        for a, b in zip(reversed(ds[:-1]), reversed(ds[1:])):
            if b.id not in out:
                head, head_attack = b, None
            if b.onset - a.end > 0.03:
                continue
            if has_attack is not None:
                if head_attack is None:
                    head_attack = has_attack(head.onset)
                if a.duration < 0.3 and head_attack and not has_attack(a.onset):
                    out.add(a.id)
            elif a.duration < 0.13 and a.amplitude < 0.6 * head.amplitude:
                out.add(a.id)
    return out


def timing_issues(results: list[NoteResult], opts: Options, issues: Issues, profile: "Profile | None" = None) -> None:
    """Timing gegen den eigenen Groove des Spielers.

    Einzeltöne zählen pro Ton, Akkorde ab dem ersten angeschlagenen Ton (das Plektrum trifft die Saiten je nach
    Up-/Downstroke nacheinander). Bewertet wird die Abweichung vom lokalen Groove – dem Median der Anschläge
    in der Umgebung –, denn gleichmäßig vor oder hinter dem Klick zu spielen ist Stil, kein Fehler. Solche
    Abschnitte erscheinen als Hinweis.
    """
    from .profile import Profile
    profile = profile or Profile()
    tp = profile.timing
    groups: dict[float, list[NoteResult]] = defaultdict(list)
    for r in results:
        if not r.note.dead:
            groups[round(r.expected_onset, 3)].append(r)
    events = []  # (lead, Gruppe, Abweichung zum Klick)
    for key in sorted(groups):
        g = groups[key]
        played = [r for r in g if r.status == "ok" and r.det is not None and not r.weak]
        if not played:
            continue
        lead = min(played, key=lambda r: r.onset)
        dt = lead.onset - lead.expected_onset
        if len(g) > 1:
            lead.chord_lead = True
            for r in g:
                r.chord_delta = dt
        events.append((lead, g, dt))
    if not events:
        return
    times = np.array([lead.expected_onset for lead, _, _ in events])
    dts = np.array([dt for _, _, dt in events])
    global_groove = float(np.median(dts))

    for k, (lead, g, dt) in enumerate(events):
        bar_len = _bar_length(issues.score, lead.note.onset)
        near = np.abs(times - times[k]) <= tp.groove_window_bars * bar_len
        near[k] = False
        groove = float(np.median(dts[near])) if near.sum() >= tp.groove_min_points else global_groove
        for r in g:
            r.groove = groove
        dev = dt - groove
        tol = opts.timing_tol * (1.5 if lead.note.legato or lead.note.harmonic else 1.0)
        if abs(dev) <= tol:
            continue
        kind = "late" if dev > 0 else "early"
        conf = 0.9 if abs(dev) > 2 * tol else 0.6
        ms = f"{abs(dev) * 1000:.0f} ms"
        context = tr(f", Groove hier {groove * 1000:+.0f} ms", f", groove here {groove * 1000:+.0f} ms") \
            if abs(groove) >= 0.008 else ""
        if len(g) > 1:
            names = "·".join(note_name(r.note.pitch) for r in sorted(g, key=lambda r: r.note.pitch))
            arrow = {"down": ", ↓", "up": ", ↑"}.get((lead.strum or {}).get("dir"), "") if profile.strum.show_direction else ""
            head = tr("Akkord zu spät", "Chord late") if dev > 0 else tr("Akkord zu früh", "Chord early")
            msg = head + f": {ms} ({names}{arrow}" + context + ")"
        else:
            head = tr("Zu spät", "Late") if dev > 0 else tr("Zu früh", "Early")
            msg = head + f": {ms} ({note_name(lead.note.pitch)}" + context + ")"
        issues.add(kind, lead.onset, msg, conf, lead.note, lead.det, delta_ms=round(dev * 1000, 1),
                   groove_ms=round(groove * 1000, 1), chord=len(g) > 1)

    _groove_hints(events, issues, tp)

    for r in results:
        if r.status != "ok" or r.det is None or r.weak:
            continue
        n = r.note
        if (not n.palm_mute and not n.dead and not n.bend and n.duration >= 0.25
                and r.det.duration < 0.4 * n.duration and r.det.duration < 0.2):
            issues.add("short", r.det.onset,
                       tr(f"Zu kurz: {r.det.duration * 1000:.0f} ms statt {n.duration * 1000:.0f} ms ({note_name(n.pitch)})",
                          f"Too short: {r.det.duration * 1000:.0f} ms instead of {n.duration * 1000:.0f} ms ({note_name(n.pitch)})"),
                       0.4, n, r.det)


def _bar_length(score: Score, t: float) -> float:
    bar, occ, _ = score.bar_at(t)
    for b in score.bars:
        if b.number == bar and b.occurrence == occ:
            return b.end - b.start
    return 2.0


def _groove_hints(events: list, issues: Issues, tp) -> None:
    """Abschnitte, die gleichmäßig vor/hinter dem Klick liegen, zusammenfassen."""
    sections: dict[int, list[float]] = defaultdict(list)
    bar_index = {(b.number, b.occurrence): k for k, b in enumerate(issues.score.bars)}
    for lead, _, dt in events:
        idx = bar_index.get((lead.note.bar, lead.note.occurrence))
        if idx is not None:
            sections[idx // tp.section_bars].append(dt)
    runs: list[list] = []  # [erster Abschnitt, letzter Abschnitt, Vorzeichen, Mediane]
    for sec in sorted(sections):
        vals = sections[sec]
        if len(vals) < 8:
            continue
        med = float(np.median(vals))
        sign = 0 if abs(med) * 1000 < tp.section_push_hint_ms else (1 if med > 0 else -1)
        if sign and runs and runs[-1][2] == sign and runs[-1][1] == sec - 1:
            runs[-1][1] = sec
            runs[-1][3].append(med)
        elif sign:
            runs.append([sec, sec, sign, [med]])
    bars = issues.score.bars
    for first, last, sign, meds in runs:
        b0 = bars[first * tp.section_bars]
        b1 = bars[min((last + 1) * tp.section_bars, len(bars)) - 1]
        avg = float(np.mean(meds)) * 1000
        where = tr("vor", "ahead of") if sign < 0 else tr("hinter", "behind")
        issues.hints.append(tr(f"T. {b0.number}–{b1.number}: spielt gleichmäßig etwa {abs(avg):.0f} ms ",
                               f"Bars {b0.number}–{b1.number}: plays consistently about {abs(avg):.0f} ms ") + where
                            + tr(" dem Klick (Stilfrage, kein Fehler – Timing wird gegen diesen Groove bewertet).",
                                 " the click (a matter of style, not an error – timing is judged against this groove)."))



def _extra_notes(results: list[NoteResult], index: _TimeIndex, taken: set[int], issues: Issues,
                 has_attack: Callable[[float], bool] | None = None) -> None:
    if not results:
        return
    start = min(r.expected_onset for r in results) - 0.5
    end = max(r.expected_onset + r.note.duration for r in results) + 0.5
    by_onset = sorted(results, key=lambda r: r.expected_onset)
    onsets = [r.expected_onset for r in by_onset]
    max_dur = max(r.note.duration for r in results)
    for d in index.notes:
        if d.id in taken or not start <= d.onset <= end:
            continue
        if d.duration < 0.06 and d.amplitude < 0.3:
            continue
        lo = bisect_left(onsets, d.onset - max_dur - 0.05)
        hi = bisect_right(onsets, d.onset + 0.05)
        sounding = [r for r in by_onset[lo:hi] if d.onset <= r.expected_onset + r.note.duration + 0.05]
        # gleicher Ton klingt laut Vorlage gerade (erneut erkannt) oder Oberton einer klingenden Note
        if any(d.pitch == r.note.pitch or d.pitch - r.note.pitch in (12, 19, 24) and d.amplitude < 0.45
               for r in sounding):
            continue
        played = [r.det.pitch for r in sounding if r.det is not None and r.det.onset - 0.03 <= d.onset <= r.det.end]
        if any(d.pitch - p in (12, 19, 24) and d.amplitude < 0.45 for p in played):
            continue
        # Vorläufer einer gleich hohen Note, die kurz darauf regulär folgt (Timing wird dort geprüft)
        if d.duration < 0.15 and any(r.det is not None and r.note.pitch == d.pitch
                                     and d.onset < r.expected_onset <= d.end + 0.15 for r in by_onset[lo:hi + 8]):
            continue
        conf = float(np.clip((d.amplitude - 0.15) / 0.35, 0.2, 0.95))
        message = tr(f"Zusätzliche Note: {note_name(d.pitch)}", f"Extra note: {note_name(d.pitch)}")
        if d.duration < 0.13:
            struck = [r for r in sounding if r.det is not None and abs(r.onset - d.onset) < 0.02 and r.det.pitch != d.pitch]
            if struck:
                conf *= 0.6
                other = note_name(struck[0].note.pitch)
                message += tr(f" (kurz, beim Anschlag von {other} – evtl. Saitengeräusch)",
                              f" (short, while picking {other} – possibly string noise)")
        if has_attack is not None and not has_attack(d.onset):
            # ohne Anschlag im Oktavabstand zu einem klingenden Ton: Erkennungsartefakt
            if any(abs(d.pitch - p) == 12 for p in [r.note.pitch for r in sounding] + played):
                continue
            # Tonhöhenschwankung (Vibrato, Bend, Intonation) einer gerade klingenden Note
            if any(abs(d.pitch - r.det.pitch) <= 2 for r in sounding if r.det is not None):
                continue
            conf *= 0.4
            message += tr(" ohne Anschlag (mitklingende Saite?)", " without attack (sympathetic string?)")
        issues.add("extra", d.onset, message, conf, None, d, played_pitch=d.pitch)
