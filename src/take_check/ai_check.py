"""KI-Check: Claude liest die Analyseergebnisse im Zusammenhang und gibt eine Einschätzung fürs Korrekturhören.

Gesendet werden nur Analysewerte (Befunde, Takte, Warnungen, Hinweise) – kein Audio und keine Vorlagendatei.
Jede Aussage der KI muss auf vorhandene Befund-IDs verweisen, damit die Oberfläche zur Stelle springen kann.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .i18n import Msg, locales, msg, render, resolve_lang

MODEL = "claude-opus-5-5"
MAX_ISSUES = 400  # Befunde mit der höchsten Sicherheit; der Rest wird nur gezählt

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


class ListenItem(BaseModel):
    title: str = Field(description="Kurzer Titel der Stelle")
    bars: str = Field(description="Taktangabe, z. B. 'T. 19–20' bzw. 'Bars 19–20'")
    reason: str = Field(description="Warum sich das Hinhören lohnt – konkret, mit Bezug auf die Befunde")
    priority: Literal["high", "medium", "low"]
    issue_ids: list[int] = Field(description="IDs der zugehörigen Befunde aus den Analysedaten")


class ArtifactItem(BaseModel):
    reason: str = Field(description="Warum das vermutlich ein Erkennungsartefakt und kein Spielfehler ist")
    issue_ids: list[int]


class AiReview(BaseModel):
    summary: str = Field(description="Einschätzung des Takes in 2–4 Sätzen")
    listen_first: list[ListenItem] = Field(description="Die wichtigsten Stellen zum Anhören, wichtigste zuerst")
    likely_artifacts: list[ArtifactItem] = Field(description="Befunde, die vermutlich Messartefakte sind")
    patterns: list[str] = Field(description="Muster über den ganzen Take (Timing, Technik, Abschnitte)")
    musician_feedback: str = Field(description="Rückmeldung an den Musiker: sachlich, konstruktiv, mit Taktangaben")


class AiCheckError(RuntimeError):
    def __init__(self, message: Msg):
        super().__init__(render(message, "en"))
        self.message = message


SYSTEM_PROMPT = """Du bist ein erfahrener Produzent und Gitarrist, der Aufnahmen von Session-Musikern Korrektur hört.
Du bekommst die Ergebnisse einer automatischen Analyse, die eine Gitarrenaufnahme mit der notierten Vorlage
vergleicht. Die Aufnahme ist eine DI-Spur: das unverzerrte Signal direkt vom Instrument, ohne Amp oder Effekte
(Verzerrung kommt erst später per Reamping/Amp-Simulation dazu). Deine Aufgabe: die Befunde im Zusammenhang einordnen, damit der Produzent gezielt hinhören kann.

So arbeitet die Analyse – berücksichtige ihre Grenzen:
- Jeder Befund hat eine Sicherheit von 0 bis 1. Niedrige Werte sind oft Erkennungsartefakte.
- Polyphone Erkennung ist bei dichten Akkorden, sehr tiefen Tönen (unter E3) und kurzen Palm-Mute-Tönen unsicher.
  Obertöne tieferer Akkordtöne können als „zusätzliche“ oder „falsche“ Töne erscheinen.
- Timing wird gegen den eigenen Groove des Spielers bewertet; gleichmäßiges Vor- oder Hinterherziehen ist Stil.
  Akkorde zählen ab der ersten angeschlagenen Saite.
- Der Handballen dämpft obere Saiten stärker; an Taktanfängen und Griffwechseln wird er oft kurz angehoben.
- Bei gedoppelten Rhythmusgitarren sind gleiche Abweichungen in mehreren Takes eher Spielweise oder eine
  ungenaue Vorlage als ein Zufallsfehler.

Regeln für deine Antwort:
- Stütze jede Aussage auf die gelieferten Daten und verweise mit issue_ids nur auf Befunde, die dort vorkommen.
- Ein Spielfehler, der nur ein einziges Mal auftritt, wiegt anders als ein wiederkehrendes Muster – sag, was davon vorliegt.
- Unterscheide klar zwischen „wahrscheinlich echter Fehler“ und „wahrscheinlich Artefakt“; wenn unklar, sag das.
- Die Rückmeldung an den Musiker ist kollegial und konkret (Takt, was auffällt, was zu tun ist), ohne Abwertung,
  und erwähnt keine vermuteten Artefakte.
- Wenn der Take sauber ist, sag das deutlich – erfinde keine Probleme."""


def _note_name(midi: int | None) -> str | None:
    return None if midi is None else f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def build_context(result: dict, lang: str = "de") -> tuple[dict, set[int]]:
    """Kompakte, JSON-fähige Sicht auf das Analyseergebnis plus die Menge der gesendeten Befund-IDs."""
    notes = {n["id"]: n for n in result["notes"]}
    chords: dict[float, list[dict]] = {}
    for n in result["notes"]:
        chords.setdefault(round(n["onset"], 3), []).append(n)

    issues = sorted(result["issues"], key=lambda i: -i["confidence"])
    sent, omitted = issues[:MAX_ISSUES], issues[MAX_ISSUES:]
    items = []
    for i in sorted(sent, key=lambda i: i["time"]):
        item = {
            "id": i["id"], "type": i["type"], "bar": i["bar"], "beat": i["beat"],
            "pass": i.get("occurrence", 1), "time_s": i["time"], "confidence": i["confidence"],
            "message": render(i.get("msg") or i.get("messages") or i.get("message"), lang),
        }
        n = notes.get(i.get("note_id"))
        if n is not None:
            item["note"] = {"pitch": _note_name(n["pitch"]), "string": n.get("string"), "fret": n.get("fret"),
                            "palm_mute": n.get("palm_mute"), "status": n.get("status")}
            group = chords.get(round(n["onset"], 3), [])
            if len(group) > 1:
                item["chord"] = [f"{_note_name(m['pitch'])}:{m['status']}" for m in sorted(group, key=lambda m: m["pitch"])]
        if i.get("played_pitch") is not None:
            item["played"] = _note_name(i["played_pitch"])
        items.append(item)

    per_bar = Counter((i["bar"], i.get("occurrence", 1)) for i in result["issues"] if i["confidence"] >= 0.5)
    context = {
        "title": result.get("title"),
        "profile": (result.get("profile") or {}).get("name"),
        "duration_s": result.get("duration"),
        "tuning": [_note_name(p) for p in result["tuning"]] if result.get("tuning") else None,
        "tuning_deviation_cents": result.get("tuning_cents"),
        "summary": result.get("summary"),
        "bars_total": len(result.get("bars", [])),
        "warnings": [render(w, lang) for w in result.get("warnings", [])],
        "hints": [render(h, lang) for h in result.get("hints", [])],
        "issues_by_type": dict(Counter(i["type"] for i in result["issues"])),
        "bars_with_confident_findings": [
            {"bar": b, "pass": occ, "count": c} for (b, occ), c in sorted(per_bar.items())],
        "issues": items,
        "issues_omitted": {"count": len(omitted), "max_confidence": max((i["confidence"] for i in omitted), default=None)},
    }
    return context, {i["id"] for i in sent}


def _key_file() -> Path:
    return Path(os.environ.get("TAKE_CHECK_API_KEY_FILE", Path.home() / ".config" / "take-check" / "anthropic_api_key"))


def _file_api_key() -> str | None:
    """API-Schlüssel aus einer Datei (z. B. außerhalb des Repositorys), falls keine Umgebungsvariable gesetzt ist."""
    path = _key_file()
    try:
        key = path.read_text().strip()
    except OSError:
        return None
    return key or None


def credentials_available() -> bool:
    """Grobe Prüfung, ob Zugangsdaten vorhanden sind: Umgebung, Schlüsseldatei oder `ant auth login`-Profil."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return _file_api_key() is not None or (Path.home() / ".config" / "anthropic").exists()


def _client():
    import anthropic
    env_set = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    key = None if env_set else _file_api_key()
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def run_ai_check(result: dict, lang: str = "de", client=None) -> dict:
    import anthropic

    lang = resolve_lang(lang)
    context, sent_ids = build_context(result, lang)
    language = locales()[lang]["meta"]["name"]
    task = (f"Hier sind die Analyseergebnisse als JSON. Antworte auf {language}.\n\n"
            f"<analysis>\n{json.dumps(context, ensure_ascii=False)}\n</analysis>")
    client = client or _client()
    try:
        response = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": task}],
            output_format=AiReview,
            output_config={"effort": "high"},
            # Lehnt das Modell ab, übernimmt serverseitig das von Anthropic empfohlene Ersatzmodell
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise AiCheckError(msg("ai_err_auth")) from exc
    except anthropic.PermissionDeniedError as exc:
        raise AiCheckError(msg("ai_err_permission")) from exc
    except anthropic.RateLimitError as exc:
        raise AiCheckError(msg("ai_err_rate")) from exc
    except anthropic.APIConnectionError as exc:
        raise AiCheckError(msg("ai_err_connection")) from exc
    except anthropic.APIStatusError as exc:
        raise AiCheckError(msg("ai_err_api", status=exc.status_code, message=exc.message)) from exc

    if response.stop_reason == "refusal":
        raise AiCheckError(msg("ai_err_refusal"))
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise AiCheckError(msg("ai_err_incomplete"))

    review = response.parsed_output.model_dump()
    # nur Verweise auf tatsächlich gesendete Befunde behalten
    dropped = 0
    for group in ("listen_first", "likely_artifacts"):
        for item in review[group]:
            valid = [i for i in item["issue_ids"] if i in sent_ids]
            dropped += len(item["issue_ids"]) - len(valid)
            item["issue_ids"] = valid
    return {
        "review": review,
        "lang": lang,
        "model": response.model,
        "request_id": getattr(response, "_request_id", None),
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        "dropped_references": dropped,
        "issues_sent": len(sent_ids),
    }
