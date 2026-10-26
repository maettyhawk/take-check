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

    s = sub.add_parser("serve", help="Web-Oberfläche starten")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("take_check.api:app", host=args.host, port=args.port)
        return 0

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


if __name__ == "__main__":
    sys.exit(main())
