"""Polyphone Transkription mit Basic Pitch (ONNX-Backend) und Zugriff auf die Posteriorgramme."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

MIDI_OFFSET = 21  # Basic Pitch: Bin 0 = A0


@dataclass
class DetectedNote:
    id: int
    onset: float
    duration: float
    pitch: int
    amplitude: float

    @property
    def end(self) -> float:
        return self.onset + self.duration


@dataclass
class Transcription:
    notes: list[DetectedNote]
    note_post: np.ndarray    # (Frames, 88) Notenaktivierung
    onset_post: np.ndarray   # (Frames, 88) Onset-Aktivierung
    frame_times: np.ndarray  # (Frames,)
    meta: dict = field(default_factory=dict)

    def evidence(self, pitch: int, t0: float, t1: float) -> float:
        """Stärkste Aktivierung der Tonhöhe im Zeitfenster – Grundlage der vorlagengestützten Prüfung."""
        col = pitch - MIDI_OFFSET
        if not 0 <= col < self.note_post.shape[1]:
            return 0.0
        i0, i1 = np.searchsorted(self.frame_times, [t0, t1])
        if i1 <= i0:
            return 0.0
        return float(max(self.note_post[i0:i1, col].max(), self.onset_post[i0:i1, col].max()))

    def save(self, path: Path) -> None:
        arr = np.array([(n.onset, n.duration, n.pitch, n.amplitude) for n in self.notes], dtype=float).reshape(-1, 4)
        np.savez_compressed(path, notes=arr, note_post=self.note_post.astype(np.float16),
                            onset_post=self.onset_post.astype(np.float16), frame_times=self.frame_times)

    @classmethod
    def load(cls, path: Path) -> "Transcription":
        d = np.load(path)
        notes = [DetectedNote(i, float(o), float(du), int(p), float(a)) for i, (o, du, p, a) in enumerate(d["notes"])]
        return cls(notes, d["note_post"].astype(np.float32), d["onset_post"].astype(np.float32), d["frame_times"])


@lru_cache(maxsize=1)
def _model():
    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.ERROR)  # Basic Pitch warnt beim Import über fehlende TF/CoreML-Backends
    try:
        from basic_pitch import FilenameSuffix, build_icassp_2022_model_path
        from basic_pitch.inference import Model
        return Model(build_icassp_2022_model_path(FilenameSuffix.onnx))
    finally:
        root.setLevel(level)


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def transcribe(audio_path: str | Path, min_pitch: int = 28, max_pitch: int = 100,
               onset_threshold: float = 0.45, frame_threshold: float = 0.3,
               min_note_ms: float = 50.0) -> Transcription:
    from basic_pitch.inference import predict
    from basic_pitch.note_creation import model_frames_to_time

    model_output, _, events = predict(
        str(audio_path), _model(),
        onset_threshold=onset_threshold, frame_threshold=frame_threshold,
        minimum_note_length=min_note_ms,
        minimum_frequency=_hz(min_pitch - 0.5), maximum_frequency=_hz(max_pitch + 0.5),
        multiple_pitch_bends=False, melodia_trick=True,
    )
    events = sorted(events, key=lambda e: (e[0], e[2]))
    notes = [DetectedNote(i, float(s), float(e - s), int(p), float(a)) for i, (s, e, p, a, _) in enumerate(events)]
    note_post = np.asarray(model_output["note"], dtype=np.float32)
    onset_post = np.asarray(model_output["onset"], dtype=np.float32)
    return Transcription(notes, note_post, onset_post, model_frames_to_time(note_post.shape[0]))
