"""Gitarren-Hilfsfunktionen: Stimmung, Saite/Bund → Tonhöhe, klingende Tonhöhe von Flageoletts."""

from __future__ import annotations

import math

STANDARD_TUNING = [40, 45, 50, 55, 59, 64]  # E2 A2 D3 G3 B3 E4, tiefste Saite zuerst

# Typische klingende Intervalle über der gegriffenen Note bei Pinch-Harmonics
PINCH_INTERVALS = (12, 19, 24, 28, 31)


def string_pitch(tuning: list[int], string: int) -> int:
    """Leersaiten-Tonhöhe; `string` 1 = höchste Saite (MusicXML/Guitar-Pro-Zählung)."""
    return tuning[len(tuning) - string]


def fretted_pitch(tuning: list[int], string: int, fret: int, capo: int = 0) -> int:
    return string_pitch(tuning, string) + capo + fret


def natural_harmonic_partial(fret: float, max_partial: int = 8, tol: float = 0.01) -> int | None:
    """Teilton, der beim Antippen über `fret` erklingt (12 → 2, 7 → 3, 5 → 4, 4 → 5 …).

    Ein Flageolett entsteht, wo der Saitenrest ein ganzzahliger Bruch k/n der Länge ist; erklingen
    tut der n-te Teilton. Gesucht wird das kleinste n, dessen Knotenpunkt nahe am Bund liegt.
    """
    if fret <= 0:
        return None
    remaining = 2 ** (-fret / 12)
    for n in range(2, max_partial + 1):
        for k in range(1, n):
            if math.gcd(k, n) == 1 and abs(remaining - k / n) < tol:
                return n
    return None


def partial_interval(n: int) -> int:
    """Halbtonabstand des n-ten Teiltons zum Grundton (gerundet auf gleichstufige Stimmung)."""
    return round(12 * math.log2(n))


def natural_harmonic_pitch(open_pitch: int, fret: float) -> int | None:
    n = natural_harmonic_partial(fret)
    return None if n is None else open_pitch + partial_interval(n)


def artificial_harmonic_pitch(fretted: int, touch_offset: int = 12) -> int:
    """Künstliches Flageolett: gegriffen + Antippen `touch_offset` Bünde höher."""
    n = natural_harmonic_partial(touch_offset)
    return fretted + (partial_interval(n) if n else 12)


NOTE_NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# Gängige Stimmungen, tiefste Saite zuerst
TUNING_PRESETS: dict[str, list[int]] = {
    "standard": STANDARD_TUNING,
    "eb standard": [39, 44, 49, 54, 58, 63],
    "d standard": [38, 43, 48, 53, 57, 62],
    "c standard": [36, 41, 46, 51, 55, 60],
    "drop d": [38, 45, 50, 55, 59, 64],
    "drop c#": [37, 44, 49, 54, 58, 63],
    "drop c": [36, 43, 48, 53, 57, 62],
    "drop b": [35, 42, 47, 52, 56, 61],
    "drop a": [33, 40, 45, 50, 54, 59],
    "open g": [38, 43, 50, 55, 59, 62],
    "open d": [38, 45, 50, 54, 57, 62],
    "dadgad": [38, 45, 50, 55, 57, 62],
    "7 standard": [35, 40, 45, 50, 55, 59, 64],
    "7 drop a": [33, 40, 45, 50, 55, 59, 64],
    "8 standard": [30, 35, 40, 45, 50, 55, 59, 64],
    "8 drop e": [28, 35, 40, 45, 50, 55, 59, 64],
    "9 standard": [25, 30, 35, 40, 45, 50, 55, 59, 64],
}


def note_to_midi(name: str) -> int:
    """'E2', 'F#1', 'Bb3' → MIDI."""
    import re
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d)", name.strip())
    if not m:
        raise ValueError(f"Ungültiger Notenname: {name!r} (erwartet z. B. E2, F#1, Bb3)")
    step, acc, octave = m.groups()
    return (int(octave) + 1) * 12 + NOTE_NAMES[step.upper()] + {"#": 1, "b": -1, "": 0}[acc]


def parse_tuning(spec: str) -> list[int]:
    """Preset-Name („Drop D“, „7 standard“) oder Notenliste tief → hoch („B1 E2 A2 D3 G3 B3 E4“)."""
    key = " ".join(spec.lower().replace("-", " ").split())
    if key in TUNING_PRESETS:
        return list(TUNING_PRESETS[key])
    parts = spec.replace(",", " ").split()
    if len(parts) < 4:
        raise ValueError(f"Unbekannte Stimmung: {spec!r}. Presets: {', '.join(TUNING_PRESETS)}")
    tuning = [note_to_midi(p) for p in parts]
    if tuning != sorted(tuning) and tuning[::-1] == sorted(tuning):
        tuning.reverse()  # hoch → tief angegeben
    return tuning
