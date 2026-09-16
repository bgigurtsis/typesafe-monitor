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
