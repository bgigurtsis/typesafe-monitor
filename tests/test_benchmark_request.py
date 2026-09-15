from scripts.benchmark_request import cost_record


def test_billed_cost_takes_precedence():
    assert cost_record({"cost": 0.03, "input_tokens": 100}, "openrouter", 4) == {
        "cost_usd": 0.03, "cost_source": "response.usage.cost",
    }


def test_typesafe_estimate_is_explicit():
    result = cost_record({"input_tokens": 500}, "typesafe", 2)
    assert result["cost_usd"] == 0.001
    assert result["cost_source"].startswith("estimate:")


def test_unknown_cost_is_not_zero():
    assert cost_record({"input_tokens": 500}, "typesafe", None)["cost_usd"] is None
    assert cost_record({"cost": True}, "openrouter", None)["cost_usd"] is None
