"""Übersetzungen: Dateien vollständig und konsistent, Rendern mit Platzhaltern, Plural und Rückfall."""

import json
import re

import pytest

from take_check import i18n
from take_check.i18n import REFERENCE, locales, msg, render, resolve_lang, to_json, ui

PLURAL = {"zero", "one", "two", "few", "many", "other"}
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _flatten(node, prefix=""):
    out = {}
    for key, value in node.items():
        if isinstance(value, dict) and not set(value) <= PLURAL:
            out.update(_flatten(value, f"{prefix}{key}."))
        else:
            out[prefix + key] = value
    return out


def _placeholders(value):
    texts = value.values() if isinstance(value, dict) else [value]
    return {name for text in texts for name in PLACEHOLDER.findall(text)}


@pytest.mark.parametrize("code", sorted(locales()))
def test_locale_is_complete_and_consistent(code):
    ref, loc = locales()[REFERENCE], locales()[code]
    assert loc["meta"]["code"] == code and loc["meta"]["name"]
    for section in ("ui", "msg"):
        ref_flat, loc_flat = _flatten(ref[section]), _flatten(loc[section])
        missing = sorted(set(ref_flat) - set(loc_flat))
        assert not missing, f"{code}: fehlende Einträge in {section}: {missing}"
        for key, value in loc_flat.items():
            assert key in ref_flat, f"{code}: unbekannter Eintrag {section}.{key}"
            assert _placeholders(value) == _placeholders(ref_flat[key]), f"{code}: Platzhalter in {section}.{key}"


def test_every_message_key_used_in_code_exists():
    import pathlib
    src = "\n".join(p.read_text() for p in pathlib.Path(i18n.__file__).parent.rglob("*.py"))
    used = set(re.findall(r'msg\(\s*"(\w+)"', src))
    used |= {k for pair in re.findall(r'msg\(\s*"(\w+)" if .*? else "(\w+)"', src) for k in pair}
    missing = sorted(used - set(locales()[REFERENCE]["msg"]))
    assert not missing, f"im Code verwendet, aber nicht übersetzt: {missing}"


def test_render_concatenation_plural_nesting_and_json_roundtrip():
    m = msg("wrong_note", played="D#3", expected="D3") + msg("suffix_octave")
    assert render(m, "de").startswith("Falscher Ton: D#3 statt D3 – Oktave daneben")
    stored = json.loads(json.dumps(to_json(m)))
    assert render(stored, "en").startswith("Wrong note: D#3 instead of D3 – off by an octave")
    one = msg("bend_missing", note="G4", amount=msg("semitones", n="1"))
    two = msg("bend_missing", note="G4", amount=msg("semitones", n="2"))
    assert render(one, "en").endswith("by 1 semitone") and render(two, "en").endswith("by 2 semitones")
    assert render(two, "de").endswith("um 2 HT gezogen werden")


def test_fallbacks():
    assert resolve_lang("de-AT") == "de" and resolve_lang("fr-FR") == REFERENCE
    assert render(msg("missing_note", note="E2"), "fr") == "Missing note: E2"  # unbekannte Sprache → Englisch
    assert render({"de": "alt", "en": "old"}, "de") == "alt"                   # Ergebnisse vor Version 3
    assert render({"k": "gibt_es_nicht"}, "de") == "gibt_es_nicht"
    assert ui("findings", "de", n=1) == "1 Befund" and ui("findings", "de", n=3) == "3 Befunde"


def test_new_language_by_file(tmp_path, monkeypatch):
    for code in ("en", "de"):
        (tmp_path / f"{code}.json").write_text((i18n.LOCALE_DIR / f"{code}.json").read_text())
    (tmp_path / "fr.json").write_text(json.dumps({"meta": {"code": "fr", "name": "Français"},
                                                  "ui": {}, "msg": {"missing_note": "Note manquante : {note}"}}))
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)
    i18n.locales.cache_clear()
    try:
        assert {"code": "fr", "name": "Français"} in i18n.languages()
        assert render(msg("missing_note", note="E2"), "fr") == "Note manquante : E2"
        assert render(msg("extra_note", note="E2"), "fr") == "Extra note: E2"  # fehlt → Englisch
    finally:
        i18n.locales.cache_clear()
