"""Time one saved request and retain its response and cost evidence locally."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

from scripts.typesafe_monitor import NoRedirect

APIS = {
    "typesafe": ("https://api.typesafe.ai/v1/systemone", "TYPESAFE_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
}


def cost_record(usage: dict, api: str, input_rate: float | None) -> dict:
    """Keep provider-reported charges distinct from price-based estimates."""
    billed = usage.get("cost")
    if type(billed) in (int, float) and math.isfinite(billed) and billed >= 0:
        return {"cost_usd": billed, "cost_source": "response.usage.cost"}
    tokens = usage.get("input_tokens")
    if api == "typesafe" and input_rate is not None and type(tokens) is int:
        return {
            "cost_usd": tokens * input_rate / 1_000_000,
            "cost_source": "estimate: billable input tokens times supplied rate",
            "input_usd_per_million": input_rate,
            "output_usd_per_million": 0,
        }
    return {"cost_usd": None, "cost_source": "unavailable"}


def run_request(api: str, source: Path, output: Path, input_rate: float | None) -> dict:
    endpoint, env_name = APIS[api]
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise ValueError(f"Set {env_name}")
    data = source.read_bytes()
    payload = json.loads(data)
    output.mkdir(parents=True, exist_ok=False)
    (output / "request.json").write_bytes(data)
    metadata = {
        "api": api,
        "endpoint": endpoint,
        "requested_model": payload["model"],
        "request_sha256": hashlib.sha256(data).hexdigest(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "timing_scope": "HTTP request through complete body read; includes network latency",
        "attempts": 1,
    }
    (output / "console.log").write_text("Starting one request; no retries.\n")
    request = urllib.request.Request(endpoint, data=data, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
    }, method="POST")
    opener = urllib.request.build_opener(NoRedirect())
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=300) as response:
            raw = response.read()
            metadata["elapsed_seconds"] = time.perf_counter() - started
            metadata["http_status"] = response.status
            metadata["request_id"] = response.headers.get("x-typesafe-request-id")
        (output / "response.json").write_bytes(raw)
        body = json.loads(raw)
        usage = body.get("usage") or {}
        metadata.update(model=body.get("model"), provider=body.get("provider"),
                        generation_id=body.get("id"), usage=usage,
                        **cost_record(usage, api, input_rate))
        metadata["status"] = "api_error" if body.get("error") else "completed"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        metadata.update(status="failed", elapsed_seconds=time.perf_counter() - started,
                        error_type=type(exc).__name__)
        if isinstance(exc, urllib.error.HTTPError):
            metadata["http_status"] = exc.code
    (output / "metrics.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", choices=APIS, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-usd-per-million", type=float)
    args = parser.parse_args()
    rate = args.input_usd_per_million
    if rate is not None and (not math.isfinite(rate) or rate < 0):
        parser.error("Input price must be finite and nonnegative")
    result = run_request(args.api, args.request, args.output, rate)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
