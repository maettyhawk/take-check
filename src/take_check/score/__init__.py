from pathlib import Path

from .model import Bar, Score, ScoreNote


def load_score(path: str | Path, tuning: list[int] | None = None) -> Score:
    """Vorlage anhand der Dateiendung laden (MusicXML/.mxl oder MIDI).

    `tuning` überschreibt die Stimmung aus der Vorlage (tiefste Saite zuerst, beliebig viele Saiten).
    """
    suffix = Path(path).suffix.lower()
    if suffix in (".mid", ".midi"):
        from .midi import parse_midi
        score = parse_midi(path)
        score.tuning = tuning
        return score
    if suffix in (".xml", ".musicxml", ".mxl"):
        from .musicxml import parse_musicxml
        return parse_musicxml(path, tuning)
    if suffix == ".gp":
        from .guitarpro import parse_gp
        return parse_gp(path, tuning)
    raise ValueError(f"Unbekanntes Vorlagenformat: {suffix} (erwartet .gp, .musicxml, .xml, .mxl, .mid)")


__all__ = ["Bar", "Score", "ScoreNote", "load_score"]
