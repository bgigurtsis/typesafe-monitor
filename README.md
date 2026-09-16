# TypeSafe monitor

**Experimental:** this is not validated for automatic security approval. The
latest run missed required abstentions on incomplete evidence; see the
[OpenInference evaluation](results.md#openinference-fp8-fallback-evaluation).

`monitor.py` reviews software-change evidence for four objectives: unauthenticated
access, privilege escalation, protected-data disclosure, and loss of audit
integrity. Each TypeSafe question has explicit true/false criteria. Optional
DeepSeek verification handles every result below the strong-alert threshold,
including very low scores: TypeSafe has missed known faults at low scores.

The monitor prints one JSON result. It creates no files or manifests and uses
only the Python 3.12 standard library.

## Run and preview

Set `TYPESAFE_API_KEY`. For DeepSeek verification, also set `OPENROUTER_API_KEY`.

```bash
python monitor.py evidence.json --deepseek
python monitor.py evidence.json --deepseek --include-io
python monitor.py evidence.json --deepseek --include-io --dry-run
```

Input is UTF-8 text or structured JSON. Include the authorized task, relevant
code, and tool calls/results. The second command includes exact provider
requests and raw responses, without HTTP authentication headers. Ordinary output
contains judgments, usage, time, and cost. Dry-run makes no network calls and
needs no keys; without `--include-io`, it prints questions without evidence.

Live calls send the complete supplied evidence to TypeSafe and, when needed and
enabled, OpenRouter. The account owner reports a **32k TypeSafe input-token
limit**. The rejection response does not report a numerical limit or token count.
An input-limit failure goes to DeepSeek with the original evidence intact.
There is no silent truncation or automatic chunking.

## Decision rule

At the default thresholds:

```text
Evidence -> TypeSafe >= 0.90 -> alert
                    < 0.90 or failure
                           |
                           v
               DeepSeek, when enabled
               |          |           |
             alert   not_flagged  needs_review
```

A TypeSafe score of at least 0.90 on any objective raises an alert. Lower scores
require an independent judgment; they cannot clear a case. Without `--deepseek`,
they return `needs_review`.

DeepSeek sees the evidence and objective definitions, never TypeSafe's scores.
It returns a probability, evidence-sufficiency flag, and short reason per
objective. A supported violation at or above `--threshold` raises an alert.
If no violation reaches the threshold and all four judgments have sufficient
evidence, the result is `not_flagged`. Missing evidence, incomplete output,
unexpected model/provider identity, and provider errors require review.
`not_flagged` applies to the supplied evidence; it is not proof that a system is safe.

These thresholds are provisional, not calibrated reliability guarantees. The
[results](results.md) distinguish synthetic checks from historical evidence.
The nested `typesafe.alert` records its original 0.5 threshold result; use the
top-level **`decision`** for the cascade's decision.

Exit status is **0** for `alert` or `not_flagged`, **2** for `needs_review`, and
**1** for local input/configuration errors. Inspect `decision` rather than using
exit status 0 as a security approval.

## Models, time, and cost

TypeSafe defaults to `--model jev-latest`. DeepSeek is fixed to
`deepseek/deepseek-v4-flash-0731`, high reasoning, through OpenRouter's
`open-inference/fp8` endpoint. Provider fallback is disabled and FP8 is required.
The response's model and provider identities are checked. FP8 is a request
constraint; the response does not independently attest to quantization.

Default `--threshold` is 0.5. Raising it above 0.90 also raises the TypeSafe
fast-alert threshold. `--input-price` defaults to the account owner's TypeSafe
rate of $0.042 per million input tokens, with free output.

Output preserves each model's HTTP time, token usage, and cost, plus the actual
end-to-end cascade time. TypeSafe cost is estimated; OpenRouter cost comes from
its response. Their sum is labeled an estimate. Missing billing stays `null`,
with a known subtotal reported separately. A skipped DeepSeek call costs zero.
Socket inactivity timeouts are 60 seconds for TypeSafe and 120 for OpenRouter.
Provider keep-alives can make total wall time longer. Neither request is retried
silently, and redirects cannot forward credentials.

## Reproducible small benchmark

`benchmark.py` contains paired synthetic faults/fixes for all four objectives,
missing-context cases, and misleading-comment controls. Example input/output behavior is checked locally and labels are never included
in model requests. That check does not prove that a supposed fix is safe for
every input; one claims fixture has an ambiguous verification boundary,
recorded in the results audit.
It runs the providers independently for comparison; cascade decisions can then
be computed from those judgments. Summing their times estimates cascade latency,
whereas `monitor.py` measures a real sequential cascade.

```bash
python benchmark.py
python benchmark.py --run > benchmark-results.json
```

The first command previews exact inputs and both requests without API calls.
The second makes paid calls with two repeats per case and prints one JSON report.
`--repeats` accepts 1-3. The report includes a fixture hash, exact requests, raw
responses, timing, and usage. It is a small diagnostic, not a production accuracy
claim. Historical inputs and earlier private runs remain Git-ignored locally.

## Checks

```bash
uv sync --locked
git config --local core.hooksPath .githooks
uv run pytest -q
uv run python -m scripts.check_ruff
```

The hook checks exact staged Python content, including partially staged files.
Ruff keeps E4, E7, E9, F, B, and PLR0915, a 50-statement function limit, unsafe
fixes disabled, and automatic fixes disabled for F401, F841, and B.

[TypeSafe API](https://docs.typesafe.ai/api) ·
[OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)
