"""Zweisprachige Texte (Deutsch/Englisch) für Befunde, Warnungen und Hinweise.

`tr("Fehlende Note", "Missing note")` ergibt einen Text, der sich wie ein String verketten lässt;
die Oberfläche zeigt die Sprache aus den Browser-/Systemeinstellungen, die Kommandozeile die aus $LANG.
"""

from __future__ import annotations

import os

LANGS = ("de", "en")


class T(dict):
    """Text in allen Sprachen; `+` verkettet sprachweise (auch mit gewöhnlichen Strings)."""

    def __add__(self, other: "T | str") -> "T":
        o = as_text(other)
        return T({lang: self[lang] + o[lang] for lang in LANGS})

    def __radd__(self, other: str) -> "T":
        return as_text(other) + self

    def __str__(self) -> str:
        return self["de"]


def tr(de: str, en: str) -> T:
    return T(de=de, en=en)


def as_text(value: "T | dict | str") -> T:
    if isinstance(value, dict):
        return T({lang: value.get(lang) or value.get("de", "") for lang in LANGS})
    return T({lang: value for lang in LANGS})


def pick(value: "T | dict | str", lang: str) -> str:
    return as_text(value)[lang if lang in LANGS else "de"]


def cli_lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v:
            return "de" if v.lower().startswith("de") else "en"
    return "de"
