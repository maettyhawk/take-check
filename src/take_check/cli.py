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
    k.add_argument("--lang", help="Sprache der Antwort, z. B. de oder en (Standard: aus $LANG)")
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
    from .i18n import cli_lang, msg, render, ui
    from .score.guitar import parse_tuning

    lang = cli_lang()

    tuning = parse_tuning(args.tuning) if args.tuning else None
    opts = Options(timing_tol=args.timing_tol / 1000) if args.timing_tol else None
    result = analyze(args.score, args.audio, opts, tuning=tuning, offset=args.offset, profile=args.profile,
                     progress=lambda stage, f: print(f"[{f:4.0%}] {ui('stages.' + stage, lang)}", file=sys.stderr))
    if args.output:
        with open(args.output, "w") as fh:
            json.dump(result, fh, ensure_ascii=False)
    summary = result["summary"]
    print("\n" + render(msg("cli_summary", title=result["title"], ok=summary["notes_ok"],
                             checked=summary["notes_checked"], offset=f"{result['offset']:+.3f}"), lang))
    for w in result["warnings"]:
        print(f"  ! {render(w, lang)}")
    for h in result["hints"]:
        print(f"  i {render(h, lang)}")
    shown = [i for i in result["issues"] if i["confidence"] >= args.min_confidence]
    for i in sorted(shown, key=lambda i: i["time"]):
        passed = msg("cli_where_pass", n=i["occurrence"]) if i["occurrence"] > 1 else ""
        where = render(msg("cli_where", bar=i["bar"], beat=f"{i['beat']:<5}", **{"pass": passed}), lang)
        print(f"  {where} {i['time']:7.2f}s  [{i['confidence']:.2f}]  {render(i.get('msg') or i['message'], lang)}")
    return 0


def _ai_check(args) -> int:
    from .ai_check import AiCheckError, credentials_available, run_ai_check
    from .i18n import cli_lang, msg, render, resolve_lang

    lang = resolve_lang(args.lang) if args.lang else cli_lang()
    t = lambda key: render(msg(key), lang)  # noqa: E731
    if not credentials_available():
        print(t("cli_no_api_key"), file=sys.stderr)
        return 2
    with open(args.result) as fh:
        result = json.load(fh)
    try:
        ai = run_ai_check(result, lang)
    except AiCheckError as exc:
        print(render(exc.message, lang), file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w") as fh:
            json.dump(ai, fh, ensure_ascii=False)
    r = ai["review"]
    print(f"\n{t('cli_ai_assessment')}:\n  {r['summary']}\n\n{t('cli_ai_listen')}:")
    for item in r["listen_first"]:
        print(f"  [{item['priority']}] {item['bars']}: {item['title']} – {item['reason']}")
    if r["likely_artifacts"]:
        print(f"\n{t('cli_ai_artifacts')}:")
        for item in r["likely_artifacts"]:
            print(f"  - {item['reason']}")
    if r["patterns"]:
        print(f"\n{t('cli_ai_patterns')}:")
        for p in r["patterns"]:
            print(f"  - {p}")
    print(f"\n{t('cli_ai_feedback')}:\n{r['musician_feedback']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
