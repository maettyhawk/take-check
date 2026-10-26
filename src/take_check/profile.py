"""Auswertungsprofile: Spielpraxis-Regeln und Schwellen aus profiles/*.toml.

Ein Profil darf nur einzelne Werte setzen; alles Übrige erbt vom Profil „standard“.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

PROFILE_DIR = Path(os.environ.get("TAKE_CHECK_PROFILES", Path(__file__).resolve().parents[2] / "profiles"))
DEFAULT = "standard"


@dataclass
class Timing:
    tolerance_ms: float = 30
    groove_window_bars: float = 1.0
    groove_min_points: int = 5
    section_bars: int = 4
    section_push_hint_ms: float = 12


@dataclass
class Strum:
    show_direction: bool = False
    report_slow: bool = False
    min_spread_ms: float = 8
    slow_ms: float = 50


@dataclass
class PalmMute:
    root_only: bool = True
    upper_tones_optional: bool = True
    local_window_s: float = 8.0
    outlier_margin: float = 0.5
    lift_points: bool = True
    lift_confidence_factor: float = 0.5


@dataclass
class Chords:
    low_pitch: int = 52
    uncertain_missing_cap: float = 0.45


@dataclass
class Stops:
    enabled: bool = True
    min_rest_ms: float = 120
    release_ms: float = 60
    anticipation_ms: float = 40
    max_level_db: float = -35
    outlier_mad: float = 2.0
    min_above_floor_db: float = 10
    natural_decay_after_s: float = 1.0
    natural_decay_factor: float = 0.5


@dataclass
class Bends:
    tolerance_cents: float = 30


@dataclass
class Profile:
    id: str = DEFAULT
    name: str = "Standard"
    description: str = ""
    timing: Timing = field(default_factory=Timing)
    strum: Strum = field(default_factory=Strum)
    palm_mute: PalmMute = field(default_factory=PalmMute)
    chords: Chords = field(default_factory=Chords)
    stops: Stops = field(default_factory=Stops)
    bends: Bends = field(default_factory=Bends)


def _apply(target, data: dict, where: str) -> None:
    known = {f.name: f for f in fields(target)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"Profil {where}: unbekannter Eintrag „{key}“")
        current = getattr(target, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"Profil {where}: [{key}] muss ein Abschnitt sein")
            _apply(current, value, f"{where}.{key}")
        else:
            setattr(target, key, type(current)(value) if not isinstance(current, bool) else bool(value))


def load_profile(profile_id: str | None = None, directory: Path | None = None) -> Profile:
    directory = directory or PROFILE_DIR
    profile_id = profile_id or DEFAULT
    if not profile_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Ungültiger Profilname: {profile_id!r}")
    profile = Profile(id=profile_id)
    for pid in dict.fromkeys([DEFAULT, profile_id]):  # erst Standard, dann Abweichungen
        path = directory / f"{pid}.toml"
        if path.exists():
            with open(path, "rb") as fh:
                _apply(profile, tomllib.load(fh), pid)
        elif pid != DEFAULT:
            raise ValueError(f"Profil „{profile_id}“ nicht gefunden ({path})")
    profile.id = profile_id
    return profile


def list_profiles(directory: Path | None = None) -> list[dict]:
    directory = directory or PROFILE_DIR
    out = []
    for path in sorted(directory.glob("*.toml")):
        p = load_profile(path.stem, directory)
        out.append({"id": p.id, "name": p.name, "description": p.description})
    return out or [{"id": DEFAULT, "name": "Standard", "description": ""}]
