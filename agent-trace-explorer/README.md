# Agent Trace Explorer

Turn an agent run into a readable static HTML report.

The Virtual Embryo Challenge Agent Team track asks teams to preserve complete trajectories, prompts, harness details, tools, permissions, budgets, and the run that produced the final prediction. Raw agent logs are usually hard to inspect. This repo makes them easier to follow without changing the underlying trace.

It is a viewer, not an evidence certifier.

## What it shows

For a run, the report shows:

- a chronological event timeline;
- task starts and finishes;
- stdout and stderr;
- tool calls when the source trace exposes them;
- artifacts and hashes;
- deterministic grades from the companion Agent Harness Lab;
- wall time and peak RSS when available;
- filters for tasks and event types.

It can also compare two runs side by side and show per-task pass/fail, duration, resource use, tool-call counts, errors, and artifacts.

The output is a single HTML file with no server and no external JavaScript.

## Supported inputs

### Virtual Embryo Agent Harness Lab JSONL

The canonical format from:

../agent-harness-lab/

### Claude Code stream JSON

Best-effort parsing of `--output-format stream-json`, including assistant text, tool uses, tool results, and the final result record.

### Generic JSONL

For other harnesses, each JSON object can use common fields such as:

```json
{"timestamp":"...","type":"tool","message":"ran scorer","task_id":"t1"}
```

The parser looks for `ts` / `timestamp`, `event` / `type`, `text` / `message` / `content`, and keeps the full original object in the report.

## Build a report

```bash
git clone https://github.com/i-habib/virtual-embryo-community
cd virtual-embryo-community/agent-trace-explorer
pip install -e .
```

```bash
trace-explorer build run/trace.jsonl -o report.html
```

Force a parser when auto-detection is ambiguous:

```bash
trace-explorer build trace.jsonl \
  --format claude \
  -o report.html
```

Formats: `auto`, `vec-bench`, `claude`, `generic`.

## Compare runs

```bash
trace-explorer compare run-a.jsonl run-b.jsonl \
  -o comparison.html
```

The comparison does not decide which run is scientifically better. It makes differences in behavior visible.

## Quick text summary

```bash
trace-explorer summary run/trace.jsonl
```

or:

```bash
trace-explorer summary run/trace.jsonl --json
```

## Demo

`examples/` contains two small Harness Lab-style traces:

- `reference.jsonl` — a clean run;
- `incomplete.jsonl` — a run with a failed task, stderr, and fewer artifacts.

Generate both HTML reports:

```bash
python examples/build_demo.py
```

## Why this is separate from evidence packaging

The Challenge already requires evidence from the exact submitted run, and community tools exist for collecting it. Trace Explorer does not create or validate that evidence. It answers a different question: **what happened during the run?**

Official Agent Team rules remain authoritative:

https://virtualembryo.ai/challenge/rules

## Tests

```bash
pip install -e '.[dev]'
pytest -q
```

## License

MIT.
