"""KI-Check ohne Netz: Platzhalter-Client im Stil des SDK."""

import json
from types import SimpleNamespace

import pytest

from take_check import ai_check
from take_check.ai_check import AiCheckError, AiReview, build_context, run_ai_check


def _result(n_issues=5):
    notes = [
        {"id": 0, "onset": 1.0, "duration": 0.5, "pitch": 43, "string": 6, "fret": 3, "palm_mute": True, "status": "ok"},
        {"id": 1, "onset": 1.0, "duration": 0.5, "pitch": 50, "string": 5, "fret": 5, "palm_mute": True, "status": "missing"},
    ]
    issues = [{"id": k, "type": "missing" if k == 0 else "extra", "time": 1.0 + k, "bar": 1 + k, "beat": 1,
               "occurrence": 1, "confidence": round(0.3 + k / (2 * n_issues), 2), "note_id": 1 if k == 0 else None,
               "message": f"Befund {k}", "messages": {"de": f"Befund {k}", "en": f"Finding {k}"}}
              for k in range(n_issues)]
    return {"title": "Test", "duration": 30.0, "tuning": [40, 45, 50, 55, 59, 64], "tuning_cents": 2.0,
            "summary": {"notes_total": 2}, "bars": [{}] * 10, "notes": notes, "issues": issues,
            "warnings": [{"de": "Warnung", "en": "Warning"}], "hints": [{"de": "Hinweis", "en": "Note"}],
            "profile": {"id": "standard", "name": "Standard"}}


class FakeMessages:
    def __init__(self, response):
        self.response, self.calls = response, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _client(review=None, stop_reason="end_turn"):
    review = review or AiReview(
        summary="Sauberer Take.",
        listen_first=[{"title": "Fehlender Ton", "bars": "T. 1", "reason": "D3 fehlt", "priority": "high",
                       "issue_ids": [0, 999]}],
        likely_artifacts=[{"reason": "Oberton", "issue_ids": [1]}],
        patterns=["Timing stabil"], musician_feedback="Takt 1: D3 mitnehmen.")
    response = SimpleNamespace(stop_reason=stop_reason, parsed_output=review if stop_reason == "end_turn" else None,
                               model="claude-opus-5-5", usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
                               _request_id="req_test")
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_context_contains_chord_and_language():
    ctx, ids = build_context(_result(), "en")
    first = next(i for i in ctx["issues"] if i["id"] == 0)
    assert first["message"] == "Finding 0" and first["note"]["pitch"] == "D3"
    assert first["chord"] == ["G2:ok", "D3:missing"]
    assert ctx["warnings"] == ["Warning"] and ctx["tuning"][0] == "E2" and ids == {0, 1, 2, 3, 4}


def test_context_limits_issues_by_confidence(monkeypatch):
    monkeypatch.setattr(ai_check, "MAX_ISSUES", 3)
    ctx, ids = build_context(_result(10), "de")
    assert len(ctx["issues"]) == 3 and ctx["issues_omitted"]["count"] == 7
    assert ids == {7, 8, 9}  # die drei sichersten


def test_request_and_reference_validation():
    client, messages = _client()
    out = run_ai_check(_result(), "de", client=client)
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_format"] is AiReview
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"] == {"effort": "high"} and "<analysis>" in call["messages"][0]["content"]
    assert out["review"]["listen_first"][0]["issue_ids"] == [0]  # erfundene ID 999 entfernt
    assert out["dropped_references"] == 1 and out["usage"]["input_tokens"] == 1200


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_refusal_and_truncation_raise(stop):
    client, _ = _client(stop_reason=stop)
    with pytest.raises(AiCheckError):
        run_ai_check(_result(), "de", client=client)


def test_api_flow_writes_result(tmp_path, monkeypatch):
    from take_check import api
    d = tmp_path / "20261027-100000-abcdef"
    d.mkdir()
    (d / "result.json").write_text(json.dumps(_result()))
    (d / "meta.json").write_text(json.dumps({"id": d.name, "status": "done", "finished": 1.0}))
    monkeypatch.setattr(api, "DATA", tmp_path)
    client, _ = _client()
    monkeypatch.setattr(ai_check, "run_ai_check", lambda result, lang: run_ai_check(result, lang, client=client))
    api._run_ai_check(d, "en")
    out = api.get_ai_check(d.name, lang="en")
    assert out["status"] == "done" and out["result"]["review"]["summary"] == "Sauberer Take." and out["stale"] is False

    monkeypatch.setattr(ai_check, "credentials_available", lambda: False)
    with pytest.raises(api.HTTPException) as err:
        api.start_ai_check(d.name, api.AiCheckRequest(lang="de"))
    assert err.value.status_code == 400
