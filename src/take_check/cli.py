"""Kommandozeile: `take-check analyze VORLAGE AUFNAHME` und `take-check serve`."""

from __future__ import annotations

import argparse
import json
import sys

from .compare import Options


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="take-check", description="Instrumentaufnahme gegen Vorlage prüfen")
    sub = parser.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Aufnahme analysieren und Fehler ausgeben")
    a.add_argument("score", help="Vorlage (.gp, .musicxml, .xml, .mxl, .mid)")
    a.add_argument("audio", help="Aufnahme (.wav, .flac, .mp3 …)")
    a.add_argument("-o", "--output", help="Ergebnis als JSON speichern")
    a.add_argument("--tuning", help="Stimmung überschreiben, z. B. 'Drop D' oder 'B1 E2 A2 D3 G3 B3 E4'")
    a.add_argument("--offset", type=float, help="Versatz in Sekunden (Audio = Vorlage + Versatz) statt automatisch")
    a.add_argument("--timing-tol", type=float, help="Timing-Toleranz in ms (Standard: aus dem Profil)")
    a.add_argument("--profile", default=None, help="Auswertungsprofil aus profiles/ (Standard: standard)")
    a.add_argument("--min-confidence", type=float, default=0.5, help="nur Meldungen ab dieser Konfidenz zeigen")

    k = sub.add_parser("ai-check", help="KI-Einschätzung zu einem gespeicherten Ergebnis (JSON aus 'analyze -o')")
    k.add_argument("result", help="Ergebnisdatei aus 'take-check analyze -o'")
    k.add_argument("--lang", choices=["de", "en"], help="Sprache der Antwort (Standard: aus $LANG)")
    k.add_argument("-o", "--output", help="KI-Check als JSON speichern")

    s = sub.add_parser("serve", help="Web-Oberfläche starten")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("take_check.api:app", host=args.host, port=args.port)
        return 0

    if args.cmd == "ai-check":
        return _ai_check(args)

    from .analyze import analyze
    from .i18n import cli_lang, pick
    from .score.guitar import parse_tuning

    lang = cli_lang()

    tuning = parse_tuning(args.tuning) if args.tuning else None
    opts = Options(timing_tol=args.timing_tol / 1000) if args.timing_tol else None
    result = analyze(args.score, args.audio, opts, tuning=tuning, offset=args.offset, profile=args.profile,
                     progress=lambda stage, f: print(f"[{f:4.0%}] {stage}", file=sys.stderr))
    if args.output:
        with open(args.output, "w") as fh:
            json.dump(result, fh, ensure_ascii=False)
    summary = result["summary"]
    if lang == "de":
        print(f"\n{result['title']}: {summary['notes_ok']}/{summary['notes_checked']} Noten ohne Befund, "
              f"Versatz {result['offset']:+.3f} s")
    else:
        print(f"\n{result['title']}: {summary['notes_ok']}/{summary['notes_checked']} notes without findings, "
              f"offset {result['offset']:+.3f} s")
    for w in result["warnings"]:
        print(f"  ! {pick(w, lang)}")
    for h in result["hints"]:
        print(f"  i {pick(h, lang)}")
    shown = [i for i in result["issues"] if i["confidence"] >= args.min_confidence]
    for i in sorted(shown, key=lambda i: i["time"]):
        if lang == "de":
            occ = f" ({i['occurrence']}. Durchgang)" if i["occurrence"] > 1 else ""
            where = f"T. {i['bar']}{occ} Zz. {i['beat']:<5}"
        else:
            occ = f" (pass {i['occurrence']})" if i["occurrence"] > 1 else ""
            where = f"Bar {i['bar']}{occ} beat {i['beat']:<5}"
        print(f"  {where} {i['time']:7.2f}s  [{i['confidence']:.2f}]  {pick(i.get('messages', i['message']), lang)}")
    return 0


def _ai_check(args) -> int:
    from .ai_check import AiCheckError, credentials_available, run_ai_check
    from .i18n import cli_lang

    lang = args.lang or cli_lang()
    if not credentials_available():
        print("Kein Anthropic-API-Schlüssel gefunden (ANTHROPIC_API_KEY setzen)." if lang == "de"
              else "No Anthropic API key found (set ANTHROPIC_API_KEY).", file=sys.stderr)
        return 2
    with open(args.result) as fh:
        result = json.load(fh)
    try:
        ai = run_ai_check(result, lang)
    except AiCheckError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w") as fh:
            json.dump(ai, fh, ensure_ascii=False)
    r = ai["review"]
    heads = {"de": ("Einschätzung", "Zuerst anhören", "Vermutlich Artefakte", "Muster", "Rückmeldung an den Musiker"),
             "en": ("Assessment", "Listen first", "Likely artifacts", "Patterns", "Feedback for the musician")}[lang]
    print(f"\n{heads[0]}:\n  {r['summary']}\n\n{heads[1]}:")
    for item in r["listen_first"]:
        print(f"  [{item['priority']}] {item['bars']}: {item['title']} – {item['reason']}")
    if r["likely_artifacts"]:
        print(f"\n{heads[2]}:")
        for item in r["likely_artifacts"]:
            print(f"  - {item['reason']}")
    if r["patterns"]:
        print(f"\n{heads[3]}:")
        for p in r["patterns"]:
            print(f"  - {p}")
    print(f"\n{heads[4]}:\n{r['musician_feedback']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
