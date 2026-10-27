"""Datenmodell der Vorlage (Score) – unabhängig vom Eingabeformat."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreNote:
    id: int
    onset: float              # Sekunden ab Beginn der Vorlage
    duration: float           # Sekunden (Haltebögen bereits zusammengeführt)
    pitch: int                # erwartete *klingende* MIDI-Tonhöhe (bei Bends: Ausgangston)
    bar: int                  # Taktnummer wie in der Vorlage
    beat: float               # Zählzeit im Takt, 1-basiert
    occurrence: int = 1       # Durchgang bei Wiederholungen
    string: int | None = None # 1 = höchste Saite
    fret: int | None = None
    fretted_pitch: int | None = None  # gegriffene Tonhöhe (nur bei Harmonics abweichend)
    palm_mute: bool = False
    legato: bool = False      # Ziel eines Hammer-on/Pull-off/Legato-Slides: kein Anschlag erwartet
    slide: bool = False
    vibrato: bool = False
    dead: bool = False        # Dead Note („x“) – keine Tonhöhe prüfbar
    let_ring: bool = False    # darf in Folgenoten/Pausen hineinklingen
    harmonic: str | None = None  # "natural" | "artificial" | "pinch"
    alt_pitches: list[int] = field(default_factory=list)  # ebenfalls akzeptierte Tonhöhen
    # Soll-Bendkurve: (Sekunden relativ zum Notenbeginn, Halbtöne über `pitch`)
    bend: list[tuple[float, float]] | None = None
    bend_timed: bool = False  # Zeitpunkte der Bendkurve stammen aus der Vorlage (sonst geschätzt)

    @property
    def end(self) -> float:
        return self.onset + self.duration

    @property
    def bend_max(self) -> float:
        return max((s for _, s in self.bend), default=0.0) if self.bend else 0.0


@dataclass
class Bar:
    number: int
    occurrence: int
    start: float
    end: float
    beats: int
    beat_type: int


@dataclass
class Score:
    notes: list[ScoreNote]
    bars: list[Bar]
    tuning: list[int] | None = None   # MIDI-Tonhöhen der leeren Saiten, tiefste zuerst
    title: str = ""
    warnings: list = field(default_factory=list)
    track_index: int = 0          # analysierte Spur in der Vorlagendatei (für die Notendarstellung im Bericht)

    def bar_at(self, t: float) -> tuple[int, int, float]:
        """(Taktnummer, Durchgang, Zählzeit) für eine Vorlagenzeit."""
        if not self.bars:
            return 0, 1, 1.0
        lo, hi = 0, len(self.bars) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.bars[mid].start <= t:
                lo = mid
            else:
                hi = mid - 1
        if t >= self.bars[lo].end - 5e-3 and lo + 1 < len(self.bars):  # Rundung am Taktende
            lo += 1
        b = self.bars[lo]
        length = max(b.end - b.start, 1e-9)
        beat = 1 + (t - b.start) / length * b.beats
        return b.number, b.occurrence, round(beat, 2)
