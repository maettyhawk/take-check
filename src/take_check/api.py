"""FastAPI-Backend der Web-Oberfläche: Upload, Analyse im Hintergrund, Ergebnisse und Audio ausliefern."""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .compare import Options
from .i18n import languages, locales, msg, resolve_lang, to_json
from .profile import list_profiles, load_profile
from .score.guitar import TUNING_PRESETS, parse_tuning

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("TAKE_CHECK_DATA", ROOT / "analyses"))
WEB = ROOT / "web"
SCORE_EXT = {".gp", ".musicxml", ".xml", ".mxl", ".mid", ".midi"}
AUDIO_EXT = {".wav", ".flac", ".aif", ".aiff", ".mp3", ".ogg", ".m4a"}
ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")

app = FastAPI(title="Take Check")
executor = ThreadPoolExecutor(max_workers=1)  # Analysen nacheinander – schont RAM/CPU der VM
ai_executor = ThreadPoolExecutor(max_workers=2)  # KI-Checks warten auf die API, nicht auf die CPU
meta_lock = Lock()


def _error(status: int, key: str, **params) -> HTTPException:
    """Fehler mit übersetzbarem Text: die Oberfläche rendert `detail` in der gewählten Sprache."""
    return HTTPException(status, to_json(msg(key, **params)))


def _dir(analysis_id: str) -> Path:
    if not ID_RE.match(analysis_id):
        raise _error(404, "err_unknown_analysis")
    d = DATA / analysis_id
    if not d.is_dir():
        raise _error(404, "err_unknown_analysis")
    return d


def _read_meta(d: Path) -> dict:
    return json.loads((d / "meta.json").read_text())


def _write_meta(d: Path, **changes) -> dict:
    with meta_lock:
        meta = _read_meta(d) if (d / "meta.json").exists() else {}
        meta.update(changes)
        tmp = d / "meta.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False))
        tmp.replace(d / "meta.json")
    return meta


def _ensure_peaks(d: Path) -> Path:
    """Wellenform-Daten anlegen bzw. veraltete (andere Version) neu berechnen."""
    from .analyze import PEAKS_VERSION, load_audio, waveform_peaks

    path = d / "peaks.json"
    if path.exists() and json.loads(path.read_text()).get("version") == PEAKS_VERSION:
        return path
    path.write_text(json.dumps(waveform_peaks(load_audio(d / _read_meta(d)["audio_file"]))))
    return path


def _run(d: Path) -> None:
    from .analyze import RESULT_VERSION, analyze

    meta = _read_meta(d)
    _write_meta(d, status="running", stage="start", progress=0.0, error=None)
    try:
        tuning = parse_tuning(meta["tuning"]) if meta.get("tuning") else None
        profile = load_profile(meta.get("profile"))
        tol_ms = meta.get("timing_tol_ms") or profile.timing.tolerance_ms
        opts = Options(timing_tol=tol_ms / 1000)
        result = analyze(d / meta["score_file"], d / meta["audio_file"], opts, tuning=tuning, profile=profile,
                         offset=meta.get("offset_manual"),
                         cache_dir=d, progress=lambda stage, f: _write_meta(d, stage=stage, progress=round(f, 2)))
        (d / "result.json").write_text(json.dumps(result, ensure_ascii=False))
        _ensure_peaks(d)
        s = result["summary"]
        _write_meta(d, status="done", stage="done", progress=1.0, title=result["title"], result_version=RESULT_VERSION,
                    offset=result["offset"], notes_checked=s["notes_checked"], notes_ok=s["notes_ok"],
                    issue_count=len(result["issues"]), issue_tiers=s["issue_tiers"], finished=time.time())
    except Exception as exc:  # Fehler für die Oberfläche festhalten
        _write_meta(d, status="error", stage="error", error=str(exc), traceback=traceback.format_exc())


@app.get("/api/tunings")
def tunings() -> dict:
    return {"presets": {name: t for name, t in TUNING_PRESETS.items()}}


def _run_ai_check(d: Path, lang: str) -> None:
    from .ai_check import AiCheckError, run_ai_check

    try:
        result = json.loads((d / "result.json").read_text())
        ai = run_ai_check(result, lang)
        ai["created"] = time.time()
        (d / f"ai_check_{lang}.json").write_text(json.dumps(ai, ensure_ascii=False))
        _write_meta(d, **{f"ai_status_{lang}": "done", f"ai_error_{lang}": None})
    except AiCheckError as exc:
        _write_meta(d, **{f"ai_status_{lang}": "error", f"ai_error_{lang}": to_json(exc.message)})
    except Exception as exc:  # unerwartet: festhalten statt den Worker zu verlieren
        _write_meta(d, **{f"ai_status_{lang}": "error",
                          f"ai_error_{lang}": to_json(msg("ai_err_unexpected", error=f"{type(exc).__name__}: {exc}"))})


class AiCheckRequest(BaseModel):
    lang: str = "de"


@app.get("/api/ai/status")
def ai_status() -> dict:
    from .ai_check import MODEL, credentials_available
    return {"configured": credentials_available(), "model": MODEL}


@app.post("/api/analyses/{analysis_id}/ai-check")
def start_ai_check(analysis_id: str, body: AiCheckRequest) -> dict:
    from .ai_check import credentials_available
    d = _dir(analysis_id)
    lang = resolve_lang(body.lang)
    if not (d / "result.json").exists():
        raise _error(409, "err_not_ready")
    if not credentials_available():
        raise _error(400, "err_no_api_key")
    if _read_meta(d).get(f"ai_status_{lang}") == "running":
        return {"status": "running"}
    _write_meta(d, **{f"ai_status_{lang}": "running", f"ai_error_{lang}": None})
    ai_executor.submit(_run_ai_check, d, lang)
    return {"status": "running"}


@app.get("/api/analyses/{analysis_id}/ai-check")
def get_ai_check(analysis_id: str, lang: str = "de") -> dict:
    d = _dir(analysis_id)
    lang = resolve_lang(lang)
    meta = _read_meta(d)
    path = d / f"ai_check_{lang}.json"
    out = {"status": meta.get(f"ai_status_{lang}", "none"), "error": meta.get(f"ai_error_{lang}")}
    if path.exists():
        out["result"] = json.loads(path.read_text())
        # Analyse neu berechnet → Befund-IDs passen nicht mehr zum KI-Check
        out["stale"] = out["result"].get("created", 0) < meta.get("finished", 0)
    return out


@app.get("/api/locales")
def list_locales() -> list[dict]:
    return languages()


@app.get("/api/locales/{code}")
def get_locale(code: str) -> dict:
    data = locales().get(code)
    if data is None:
        raise HTTPException(404, "unknown locale")
    return data


@app.get("/api/profiles")
def profiles() -> list[dict]:
    return list_profiles()


def _ai_checks(d: Path, meta: dict) -> list[dict]:
    """Vorhandene bzw. laufende KI-Checks je Sprache; veraltet, wenn die Analyse danach neu berechnet wurde."""
    checks = []
    for code in sorted({p.stem.removeprefix("ai_check_") for p in d.glob("ai_check_*.json")}
                       | {k.removeprefix("ai_status_") for k, v in meta.items() if k.startswith("ai_status_") and v == "running"}):
        path = d / f"ai_check_{code}.json"
        running = meta.get(f"ai_status_{code}") == "running"
        stale = path.exists() and path.stat().st_mtime < meta.get("finished", 0)
        checks.append({"lang": code, "running": running, "done": path.exists(), "stale": stale})
    return checks


@app.get("/api/analyses")
def list_analyses() -> list[dict]:
    if not DATA.exists():
        return []
    from .analyze import issue_tiers
    metas = []
    for d in DATA.iterdir():
        if ID_RE.match(d.name) and (d / "meta.json").exists():
            m = _read_meta(d)
            if m.get("status") == "done" and "issue_tiers" not in m and (d / "result.json").exists():
                # ältere Analysen: Sicherheitsstufen einmalig aus dem Ergebnis nachtragen
                tiers = issue_tiers(json.loads((d / "result.json").read_text())["issues"])
                m = _write_meta(d, issue_tiers=tiers)
            m.pop("traceback", None)
            m["ai_checks"] = _ai_checks(d, m)
            metas.append(m)
    return sorted(metas, key=lambda m: m.get("created", 0), reverse=True)


@app.post("/api/analyses")
async def create_analysis(score: UploadFile = File(...), audio: UploadFile = File(...),
                          tuning: str = Form(""), timing_tol_ms: float | None = Form(None),
                          profile: str = Form("standard")) -> dict:
    s_ext = Path(score.filename or "").suffix.lower()
    a_ext = Path(audio.filename or "").suffix.lower()
    if s_ext not in SCORE_EXT:
        raise _error(400, "err_score_ext", exts=", ".join(sorted(SCORE_EXT)))
    if a_ext not in AUDIO_EXT:
        raise _error(400, "err_audio_ext", exts=", ".join(sorted(AUDIO_EXT)))
    if tuning.strip():
        try:
            parse_tuning(tuning)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    try:
        load_profile(profile)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    analysis_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    d = DATA / analysis_id
    d.mkdir(parents=True)
    for upload, name in ((score, f"score{s_ext}"), (audio, f"audio{a_ext}")):
        with open(d / name, "wb") as fh:
            shutil.copyfileobj(upload.file, fh, length=1 << 20)
    _write_meta(d, id=analysis_id, created=time.time(), status="queued", stage="queued", progress=0.0,
                score_name=score.filename, audio_name=audio.filename, score_file=f"score{s_ext}",
                audio_file=f"audio{a_ext}", tuning=tuning.strip() or None, timing_tol_ms=timing_tol_ms,
                profile=profile)
    executor.submit(_run, d)
    return {"id": analysis_id}


class Rerun(BaseModel):
    offset: float | None = None      # manueller Versatz (bleibt für spätere Neuberechnungen gespeichert)
    reset_offset: bool = False       # wieder automatisch bestimmen
    tuning: str | None = None


@app.post("/api/analyses/{analysis_id}/rerun")
def rerun(analysis_id: str, body: Rerun) -> dict:
    d = _dir(analysis_id)
    if body.tuning is not None:
        if body.tuning.strip():
            try:
                parse_tuning(body.tuning)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
        _write_meta(d, tuning=body.tuning.strip() or None)
    if body.reset_offset:
        _write_meta(d, offset_manual=None)
    elif body.offset is not None:
        _write_meta(d, offset_manual=body.offset)
    _write_meta(d, status="queued", stage="queued", progress=0.0)
    executor.submit(_run, d)
    return {"id": analysis_id}


@app.get("/api/analyses/{analysis_id}")
def get_meta(analysis_id: str) -> dict:
    from .analyze import RESULT_VERSION
    meta = _read_meta(_dir(analysis_id))
    meta.pop("traceback", None)
    meta["outdated"] = meta.get("status") == "done" and meta.get("result_version", 1) < RESULT_VERSION
    return meta


@app.get("/api/analyses/{analysis_id}/result")
def get_result(analysis_id: str):
    path = _dir(analysis_id) / "result.json"
    if not path.exists():
        raise _error(404, "err_no_result")
    return FileResponse(path, media_type="application/json")


@app.get("/api/analyses/{analysis_id}/peaks")
def get_peaks(analysis_id: str):
    d = _dir(analysis_id)
    if not (d / "result.json").exists():
        raise _error(404, "err_no_peaks")
    return FileResponse(_ensure_peaks(d), media_type="application/json")


@app.get("/api/analyses/{analysis_id}/score")
def get_score(analysis_id: str):
    d = _dir(analysis_id)
    return FileResponse(d / _read_meta(d)["score_file"], media_type="application/octet-stream")


class ReportState(BaseModel):
    issue_ids: list[str] | None = None
    feedback: str | None = None
    timing_tol_ms: float | None = None
    source: str | None = None   # Herkunft der Auswahl: user, ai, confident
    auto: bool | None = None    # automatisch vorbelegt, noch nicht von Hand geändert
    clef: str | None = None     # Notenschlüssel im Bericht: auto, treble8, bass, score
    comments: dict[str, str] | None = None  # Anmerkungen je Befund-ID (stehen im Bericht unter dem Befund)


@app.get("/api/analyses/{analysis_id}/report")
def get_report(analysis_id: str) -> dict:
    """Auswahl und Feedbacktext des Musiker-Berichts; leer, solange nichts gespeichert wurde."""
    d = _dir(analysis_id)
    path = d / "report.json"
    if not path.exists():
        return {}
    report = json.loads(path.read_text())
    # Analyse neu berechnet → Befund-IDs passen nicht mehr; der Feedbacktext bleibt
    if report.get("finished") != _read_meta(d).get("finished"):
        report.pop("issue_ids", None)
    return report


@app.put("/api/analyses/{analysis_id}/report")
def put_report(analysis_id: str, body: ReportState) -> dict:
    d = _dir(analysis_id)
    path = d / "report.json"
    report = get_report(analysis_id)
    report.update(body.model_dump(exclude_unset=True))
    report["finished"] = _read_meta(d).get("finished")
    tmp = d / "report.json.tmp"
    tmp.write_text(json.dumps(report, ensure_ascii=False))
    tmp.replace(path)
    return report


@app.get("/api/analyses/{analysis_id}/report.pdf")
def get_report_pdf(analysis_id: str, request: Request, lang: str = "de") -> Response:
    from .report_pdf import PdfError, render_pdf
    d = _dir(analysis_id)
    meta = _read_meta(d)
    if meta.get("status") != "done":
        raise _error(409, "err_not_ready")
    lang = resolve_lang(lang)
    port = request.scope["server"][1]  # die eigene Oberfläche, egal über welchen Host der Browser kommt
    try:
        pdf = render_pdf(f"http://127.0.0.1:{port}/#/a/{analysis_id}/report/print", lang)
    except PdfError as exc:
        raise HTTPException(503, to_json(exc.message))
    name = f"{meta.get('title') or 'take'} - {Path(meta['audio_name']).stem}"
    name = re.sub(r"[^\w.-]+", "_", name, flags=re.ASCII).strip("_")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})


@app.get("/api/analyses/{analysis_id}/audio")
def get_audio(analysis_id: str):
    d = _dir(analysis_id)
    return FileResponse(d / _read_meta(d)["audio_file"])


@app.delete("/api/analyses/{analysis_id}")
def delete_analysis(analysis_id: str) -> JSONResponse:
    d = _dir(analysis_id)
    if _read_meta(d).get("status") in ("queued", "running"):
        raise _error(409, "err_analysis_running")
    shutil.rmtree(d)
    return JSONResponse({"deleted": analysis_id})


class _RevalidatingStatic(StaticFiles):
    """Browser soll die Oberfläche bei jedem Laden auf Aktualität prüfen (sonst bleibt nach Updates altes JS)."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", _RevalidatingStatic(directory=WEB, html=True), name="web")
