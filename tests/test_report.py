"""Musiker-Bericht: Auswahl speichern, nach Neuberechnung verwerfen, PDF-Fehler übersetzbar melden."""

import json

import pytest

from take_check import api, report_pdf


@pytest.fixture
def analysis(tmp_path, monkeypatch):
    d = tmp_path / "20261027-100000-abcdef"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"id": d.name, "status": "done", "finished": 1.0,
                                             "title": "Song", "audio_name": "Take 1.wav"}))
    monkeypatch.setattr(api, "DATA", tmp_path)
    return d


def test_report_selection_roundtrip(analysis):
    assert api.get_report(analysis.name) == {}
    api.put_report(analysis.name, api.ReportState(issue_ids=["3", "t12"], timing_tol_ms=30))
    # Felder, die fehlen, bleiben erhalten
    api.put_report(analysis.name, api.ReportState(feedback="Bitte Takt 7 nochmal."))
    report = api.get_report(analysis.name)
    assert report["issue_ids"] == ["3", "t12"] and report["feedback"] == "Bitte Takt 7 nochmal."


def test_report_selection_dropped_after_rerun(analysis):
    api.put_report(analysis.name, api.ReportState(issue_ids=["3"], feedback="Text"))
    api._write_meta(analysis, finished=2.0)
    report = api.get_report(analysis.name)
    assert "issue_ids" not in report and report["feedback"] == "Text"


class _Request:
    scope = {"server": ("127.0.0.1", 8123)}


def test_report_pdf(analysis, monkeypatch):
    calls = []
    monkeypatch.setattr(report_pdf, "render_pdf", lambda url, lang: calls.append((url, lang)) or b"%PDF-1.7")
    res = api.get_report_pdf(analysis.name, _Request(), lang="en")
    assert res.body == b"%PDF-1.7"
    assert calls == [(f"http://127.0.0.1:8123/#/a/{analysis.name}/report/print", "en")]
    assert 'filename="Song_-_Take_1.pdf"' in res.headers["content-disposition"]

    def unavailable(url, lang):
        raise report_pdf.PdfError(report_pdf.msg("err_pdf_unavailable"))
    monkeypatch.setattr(report_pdf, "render_pdf", unavailable)
    with pytest.raises(api.HTTPException) as err:
        api.get_report_pdf(analysis.name, _Request(), lang="de")
    assert err.value.status_code == 503 and err.value.detail["k"] == "err_pdf_unavailable"
