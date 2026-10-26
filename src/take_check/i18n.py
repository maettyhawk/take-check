"""Übersetzungen aus `locales/*.json` – eine Datei pro Sprache, gemeinsam für Oberfläche und Analyse.

Die Analyse erzeugt keine fertigen Sätze, sondern Textschlüssel mit Parametern (`msg("missing_note", note="D3")`).
Ergebnisse speichern diese Schlüssel; übersetzt wird erst beim Anzeigen (Browser, Kommandozeile, KI-Check).
Eine neue Sprache = eine neue JSON-Datei; fehlende Einträge fallen auf Englisch zurück.

Textvorlagen nutzen `{name}`-Platzhalter. Pluralformen sind Objekte nach Intl-Kategorien
(`{"one": "…", "other": "…"}`), gewählt über den Parameter `n`.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

LOCALE_DIR = Path(os.environ.get("TAKE_CHECK_LOCALES", Path(__file__).parent / "locales"))
REFERENCE = "en"
PLURAL_KEYS = {"zero", "one", "two", "few", "many", "other"}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@lru_cache(maxsize=1)
def locales() -> dict[str, dict]:
    out = {}
    for path in sorted(LOCALE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[data.get("meta", {}).get("code", path.stem)] = data
    if REFERENCE not in out:
        raise RuntimeError(f"Referenzsprache {REFERENCE}.json fehlt in {LOCALE_DIR}")
    return out


def languages() -> list[dict]:
    return [{"code": code, "name": data.get("meta", {}).get("name", code)} for code, data in locales().items()]


def resolve_lang(lang: str | None) -> str:
    """Sprachcode auf eine vorhandene Datei abbilden ('de-AT' → 'de'); sonst Englisch."""
    available = locales()
    if lang:
        lang = lang.replace("_", "-").lower()
        if lang in available:
            return lang
        base = lang.split("-")[0]
        if base in available:
            return base
    return REFERENCE


class Msg:
    """Übersetzbarer Text: Schlüssel plus Parameter; `+` verkettet zu einer Folge."""

    __slots__ = ("key", "params")

    def __init__(self, key: str, params: dict):
        self.key, self.params = key, params

    def __add__(self, other) -> "MsgSeq":
        return MsgSeq([self]) + other

    def __radd__(self, other) -> "MsgSeq":
        return MsgSeq([other, self]) if other else MsgSeq([self])

    def to_json(self) -> dict:
        return {"k": self.key, "p": {name: to_json(value) for name, value in self.params.items()}} if self.params \
            else {"k": self.key}

    def __str__(self) -> str:
        return render(self, REFERENCE)

    def __repr__(self) -> str:
        return f"msg({self.key!r}, {self.params!r})"


class MsgSeq:
    __slots__ = ("parts",)

    def __init__(self, parts: list):
        self.parts = [p for p in parts if p not in ("", None)]

    def __add__(self, other) -> "MsgSeq":
        extra = other.parts if isinstance(other, MsgSeq) else [other]
        return MsgSeq(self.parts + extra)

    def __radd__(self, other) -> "MsgSeq":
        return MsgSeq([other] + self.parts)

    def to_json(self) -> list:
        return [to_json(p) for p in self.parts]

    def __str__(self) -> str:
        return render(self, REFERENCE)


def msg(key: str, **params) -> Msg:
    return Msg(key, params)


def to_json(value):
    """JSON-fähige Form für Ergebnisse: Msg → {"k", "p"}, Folge → Liste, sonst unverändert."""
    if isinstance(value, (Msg, MsgSeq)):
        return value.to_json()
    return value


def _lookup(section: str, key: str, lang: str):
    for code in (lang, REFERENCE):
        node = locales().get(code, {}).get(section, {})
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if node is not None:
            return node
    return None


def _plural(template, params: dict) -> str:
    if not isinstance(template, dict):
        return template
    n = params.get("n")
    try:
        category = "one" if float(n) == 1 else "other"
    except (TypeError, ValueError):
        category = "other"
    return template.get(category) or template.get("other") or next(iter(template.values()))


def format_template(template, params: dict, lang: str) -> str:
    text = _plural(template, params)
    return _PLACEHOLDER.sub(lambda m: render(params[m.group(1)], lang) if m.group(1) in params else m.group(0), text)


def render(value, lang: str = REFERENCE) -> str:
    """Text in einer Sprache: Msg/Folge, gespeichertes JSON ({"k","p"} bzw. Liste), alte {de,en}-Texte oder Strings."""
    if value is None:
        return ""
    if isinstance(value, (Msg, MsgSeq)):
        value = value.to_json()
    if isinstance(value, list):
        return "".join(render(part, lang) for part in value)
    if isinstance(value, dict):
        if "k" in value:
            template = _lookup("msg", value["k"], lang)
            return value["k"] if template is None else format_template(template, value.get("p", {}), lang)
        return value.get(lang) or value.get(REFERENCE) or value.get("de", "")  # Ergebnisse vor Version 3
    return str(value)


def ui(key: str, lang: str = REFERENCE, **params) -> str:
    template = _lookup("ui", key, lang)
    return key if template is None else format_template(template, params, lang)


def cli_lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            return resolve_lang(value.split(".")[0])
    return resolve_lang("de")
