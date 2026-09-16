# TypeSafe monitor

`monitor.py` asks four independent security questions in one TypeSafe request:
unauthenticated access, privilege escalation, protected-data disclosure, and loss
of audit integrity. It prints one JSON result. It creates no files or manifests.

## Run

Python 3.12 or newer; the monitor uses only the standard library.
Set `TYPESAFE_API_KEY` in your environment, then:

```bash
python monitor.py evidence.txt
python monitor.py evidence.txt --threshold 0.5
python monitor.py evidence.txt --dry-run
```

Input is UTF-8 text, or a `.json` file containing structured evidence. Live calls
send the entire input to TypeSafe. Use only material you are willing to share
with the provider. Dry-run needs no key and prints the questions without evidence.

Output includes each objective's probability, an alert if **any** reaches the
threshold, elapsed HTTP seconds, token usage, and estimated cost. There is no
combined attack probability: the alert is a simple threshold rule.

Defaults: `--model jev-latest`, `--threshold 0.5`, and `--input-price 0.042`
USD per million input tokens, with free output. The price was supplied by the
account owner; change it if your rate differs. Cost is estimated, not a billing
receipt. Timing includes network overhead. A request times out after 60 seconds,
with no automatic retries. The account owner reports a **32k input-token limit**;
this is user-supplied information, not a limit independently verified in the
public API schema. Budget for evidence and questions together. The rejection
response does not include a numerical limit or token count. Missing or invalid
answers fail with exit status 1.
Completed evaluations exit 0; inspect `alert` for the decision.

There is no native-transcript parser or automatic chunking. The full historical
interval we tried exceeded TypeSafe's input limit. The smaller excerpt exposed
an important detection weakness; see [results](results.md). Separate objective
questions did not reliably distinguish that attack from a one-line fixed copy.
All four default questions include explicit true/false criteria. Narrow
field-value questions benefited from adding criteria, but the improvement
weakened when the surrounding code was restored; see the
[scope experiments](results.md#smaller-inputs-and-explicit-criteria).

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

[TypeSafe API](https://docs.typesafe.ai/api) Â·
[Question design](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
