"""Offline checks for the standalone TypeSafe monitor."""

import pytest

from scripts.typesafe_monitor import build_request, main, summarize


def test_request_keeps_evidence_separate():
    request = build_request("untrusted transcript", "jev-latest")
    assert request["state"] == {"evidence": "untrusted transcript"}
    assert request["questions"]["suspicious"]["type"] == "noul"


@pytest.mark.parametrize("value", [None, True, "0.5", -1, 2, float("nan")])
def test_invalid_probability_is_not_a_clean_result(value):
    with pytest.raises(ValueError, match="invalid monitor answer"):
        summarize({"model": "jev", "answers": {
            "suspicious": {"type": "noul", "noul": value},
        }}, 0.5)


def test_missing_answer_fails():
    with pytest.raises(ValueError):
        summarize({}, 0.5)


def test_threshold_boundary():
    response = {"model": "jev", "answers": {
        "suspicious": {"type": "noul", "noul": 0.5},
    }}
    assert summarize(response, 0.5)["alert"] is True
    assert summarize(response, 0.6)["alert"] is False


def test_dry_run_needs_no_key(tmp_path, monkeypatch, capsys):
    source = tmp_path / "evidence.txt"
    source.write_text("ordinary coding work", encoding="utf-8")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["monitor", str(source), "--dry-run"])
    assert main() == 0
    output = capsys.readouterr().out
    assert '"dry_run": true' in output
    assert "ordinary coding work" not in output
