import io
import json
import urllib.error

import pytest

import monitor


def reply(value=0.1):
    return {
        "model": "jev-test",
        "answers": {name: {"type": "noul", "noul": value} for name in monitor.QUESTIONS},
        "usage": {"input_tokens": 1000, "output_tokens": 50},
    }


def test_four_independent_questions():
    request = monitor.build_request({"code": "example"})
    assert request["state"] == {"code": "example"}
    assert len(request["questions"]) == 4
    assert all(q["type"] == "noul" for q in request["questions"].values())


def test_any_objective_can_alert():
    response = reply()
    response["answers"]["audit_integrity_loss"]["noul"] = 0.5
    result = monitor.summarize(response, 1.2, 0.5, 0.042)
    assert result["alert"] is True
    assert result["estimated_cost_usd"] == pytest.approx(0.000042)
    assert result["elapsed_seconds"] == 1.2
    assert monitor.summarize(response, 1.2, 0.6, 0.042)["alert"] is False


@pytest.mark.parametrize("value", [None, True, "0.5", -1, 2, float("nan")])
def test_bad_probability_fails(value):
    with pytest.raises(ValueError, match="Invalid or incomplete"):
        monitor.summarize(reply(value), 1, 0.5, 0.042)


def test_missing_objective_fails():
    response = reply()
    del response["answers"]["unauthenticated_access"]
    with pytest.raises(ValueError):
        monitor.summarize(response, 1, 0.5, 0.042)


@pytest.mark.parametrize("usage", [{}, {"input_tokens": -1, "output_tokens": 2},
                                   {"input_tokens": True, "output_tokens": 2}])
def test_invalid_usage_fails(usage):
    response = {**reply(), "usage": usage}
    with pytest.raises(ValueError):
        monitor.summarize(response, 1, 0.5, 0.042)


def test_dry_run_needs_no_key(tmp_path, monkeypatch, capsys):
    source = tmp_path / "evidence.txt"
    source.write_text("private evidence", encoding="utf-8")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["monitor", str(source), "--dry-run"])
    assert monitor.main() == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["dry_run"] is True
    assert result["questions"] == monitor.build_request("private evidence")["questions"]
    assert "private evidence" not in output


def test_invalid_json_state_fails(tmp_path, monkeypatch, capsys):
    source = tmp_path / "evidence.json"
    source.write_text("null")
    monkeypatch.setattr("sys.argv", ["monitor", str(source), "--dry-run"])
    assert monitor.main() == 1
    assert "nonempty" in capsys.readouterr().err


def test_http_payload_and_timer(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == monitor.ENDPOINT
            assert request.get_header("Authorization") == "Bearer test-key"
            assert len(json.loads(request.data)["questions"]) == 4
            assert timeout == 60
            return io.BytesIO(json.dumps(reply()).encode())

    ticks = iter([10, 10.75])
    monkeypatch.setattr(monitor.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(monitor.urllib.request, "build_opener", lambda handler: Opener())
    response, seconds = monitor.evaluate(monitor.build_request("evidence"), "test-key")
    assert seconds == 0.75
    assert response["model"] == "jev-test"


def test_http_error_does_not_expose_body(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(monitor.ENDPOINT, 401, "secret", {}, io.BytesIO(b"secret"))

    monkeypatch.setattr(monitor.urllib.request, "build_opener", lambda handler: Opener())
    with pytest.raises(RuntimeError, match="^TypeSafe returned HTTP 401$"):
        monitor.evaluate(monitor.build_request("evidence"), "test-key")


def test_redirect_is_refused():
    assert monitor.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other") is None


@pytest.mark.parametrize("body", [
    b'{"detail":{"error_type":"max_tokens_exceeded"}}',
    b'{"detail":"private error text"}',
    b'["unexpected shape"]',
])
def test_input_limit_error_is_safe_and_specific(monkeypatch, body):
    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(monitor.ENDPOINT, 400, "private", {}, io.BytesIO(body))

    monkeypatch.setattr(monitor.urllib.request, "build_opener", lambda handler: Opener())
    with pytest.raises(RuntimeError) as error:
        monitor.evaluate(monitor.build_request("evidence"), "test-key")
    message = str(error.value)
    if b"max_tokens_exceeded" in body:
        assert "max_tokens_exceeded" in message
        assert "did not report its limit" in message
    else:
        assert message == "TypeSafe returned HTTP 400"


def deepseek_reply(value=0.05, sufficient=True):
    judgments = {name: {"probability": value, "evidence_sufficient": sufficient,
                        "reason": "Visible implementation preserves this requirement."}
                 for name in monitor.QUESTIONS}
    return {"model": monitor.DEEPSEEK_MODEL, "provider": "OpenInference",
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(judgments)}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.00009}}


def test_deepseek_request_is_pinned_and_independent():
    request = monitor.build_deepseek_request({"code": "evidence"})
    assert request["provider"]["only"] == ["open-inference/fp8"]
    assert request["provider"]["quantizations"] == ["fp8"]
    assert request["provider"]["allow_fallbacks"] is False
    assert request["response_format"]["json_schema"]["strict"] is True
    assert json.loads(request["messages"][1]["content"]) == {"code": "evidence"}
    assert "TypeSafe" not in request["messages"][0]["content"]


@pytest.mark.parametrize("value,sufficient,expected", [
    (0.05, True, "not_flagged"), (0.9, True, "alert"),
    (0.05, False, "needs_review"), (0.9, False, "needs_review"),
])
def test_deepseek_decision_requires_evidence(value, sufficient, expected):
    result = monitor.summarize_deepseek(deepseek_reply(value, sufficient), 1, 0.5)
    assert result["decision"] == expected


@pytest.mark.parametrize("field,value", [("provider", "BaseTen"), ("model", "different-model")])
def test_unexpected_deepseek_identity_fails(field, value):
    response = deepseek_reply()
    response[field] = value
    with pytest.raises(ValueError, match="unexpected-route"):
        monitor.summarize_deepseek(response, 1, 0.5)


@pytest.mark.parametrize("finish", ["length", "error", None])
def test_incomplete_deepseek_completion_fails(finish):
    response = deepseek_reply()
    response["choices"][0]["finish_reason"] = finish
    with pytest.raises(ValueError):
        monitor.summarize_deepseek(response, 1, 0.5)


@pytest.mark.parametrize("value", [True, "0.5", float("nan"), -0.1, 1.1])
def test_invalid_deepseek_probability_fails(value):
    with pytest.raises(ValueError):
        monitor.summarize_deepseek(deepseek_reply(value), 1, 0.5)


@pytest.mark.parametrize("content", [None, '', '{}', '[]', 'null', 'not JSON'])
def test_missing_or_malformed_deepseek_judgments_fail(content):
    response = deepseek_reply()
    response["choices"][0]["message"]["content"] = content
    with pytest.raises(ValueError):
        monitor.summarize_deepseek(response, 1, 0.5)


def test_all_low_typesafe_scores_still_require_review():
    typesafe = monitor.summarize(reply(0.01), 1, 0.5, 0.042)
    assert monitor.combine_judgments(typesafe, None, 0.5) == "needs_review"
    assert monitor.combine_judgments(typesafe, {"decision": "alert"}, 0.5) == "alert"


def test_cascade_calls_deepseek_after_low_score(monkeypatch):
    calls = []

    def fake_evaluate(payload, key, **kwargs):
        calls.append((payload, key, kwargs))
        return (reply(0.05), 0.2) if len(calls) == 1 else (deepseek_reply(0.95), 2.5)

    monkeypatch.setattr(monitor, "evaluate", fake_evaluate)
    result = monitor.review("private evidence", "ts-key", openrouter_key="or-key", include_io=True)
    assert len(calls) == 2
    assert result["decision"] == "alert"
    assert result["typesafe"]["alert"] is False
    assert result["deepseek"]["decision"] == "alert"
    assert result["cost"]["combined_estimated_usd"] == pytest.approx(0.000132)
    assert result["typesafe"]["elapsed_seconds"] == 0.2
    assert result["deepseek"]["elapsed_seconds"] == 2.5
    assert "ts-key" not in json.dumps(result)
    assert "or-key" not in json.dumps(result)


def test_strong_typesafe_alert_skips_fallback(monkeypatch):
    def fake_evaluate(payload, key, **kwargs):
        assert key == "ts-key"
        return reply(0.95), 0.2

    monkeypatch.setattr(monitor, "evaluate", fake_evaluate)
    result = monitor.review("evidence", "ts-key", openrouter_key="or-key")
    assert result["decision"] == "alert"
    assert result["deepseek"] is None
    assert result["cost"]["openrouter_reported_usd"] == 0


def test_typesafe_failure_still_uses_full_evidence_for_deepseek(monkeypatch):
    calls = []

    def fake_evaluate(payload, key, **kwargs):
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("TypeSafe input limit exceeded (max_tokens_exceeded)")
        return deepseek_reply(), 1

    monkeypatch.setattr(monitor, "evaluate", fake_evaluate)
    evidence = {"interval": "all original evidence"}
    result = monitor.review(evidence, "ts", openrouter_key="or")
    assert json.loads(calls[1]["messages"][1]["content"]) == evidence
    assert result["decision"] == "not_flagged"
    assert result["fallback_reason"] == "typesafe_failed"
    assert result["cost"]["combined_estimated_usd"] is None
    assert result["cost"]["known_subtotal_usd"] == 0.00009


def test_failed_fallback_never_clears(monkeypatch):
    def fake_evaluate(payload, key, **kwargs):
        if key == "ts":
            return reply(0.01), 0.1
        raise RuntimeError("OpenRouter returned HTTP 429")

    monkeypatch.setattr(monitor, "evaluate", fake_evaluate)
    result = monitor.review("evidence", "ts", openrouter_key="or")
    assert result["decision"] == "needs_review"
    assert result["cost"]["openrouter_reported_usd"] is None


def test_truncated_response_preserves_reported_cost(monkeypatch):
    response = deepseek_reply()
    response["choices"][0]["finish_reason"] = "length"
    monkeypatch.setattr(monitor, "evaluate", lambda payload, key, **kw:
                        (reply(0.01), 0.1) if key == "ts" else (response, 2))
    result = monitor.review("evidence", "ts", openrouter_key="or", include_io=True)
    assert result["decision"] == "needs_review"
    assert result["cost"]["openrouter_reported_usd"] == 0.00009
    assert result["responses"]["deepseek"] == response


def test_dry_run_can_preview_both_exact_requests(tmp_path, monkeypatch, capsys):
    source = tmp_path / "evidence.json"
    source.write_text('{"code":"example"}')
    monkeypatch.setattr("sys.argv", ["monitor", str(source), "--deepseek", "--include-io", "--dry-run"])
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert monitor.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["requests"]["typesafe"]["state"] == {"code": "example"}
    assert json.loads(output["requests"]["deepseek"]["messages"][1]["content"]) == {"code": "example"}


def test_cli_review_exit_status(tmp_path, monkeypatch, capsys):
    source = tmp_path / "evidence.txt"
    source.write_text("example")
    monkeypatch.setattr("sys.argv", ["monitor", str(source)])
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-key")
    monkeypatch.setattr(monitor, "evaluate", lambda payload, key: (reply(0.01), 0.1))
    assert monitor.main() == 2
    assert json.loads(capsys.readouterr().out)["decision"] == "needs_review"


def test_benchmark_labels_and_identifiers():
    import benchmark

    rows = benchmark.cases()
    assert len(rows) == 20
    assert len({row["id"] for row in rows}) == len(rows)
    assert sum(row["expected"] == "needs_review" for row in rows) == 2
    for row in rows:
        request = benchmark.requests_for(row)
        assert "expected" not in request["typesafe"]["state"]
        assert "split" not in request["typesafe"]["state"]
