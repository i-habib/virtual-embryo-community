# Agent Trace Explorer

Agent Trace Explorer turns the trace of one agent run into a single static HTML report. Its main input is the `trace.jsonl` written by the companion [Agent Harness Lab](../agent-harness-lab/), which records each task's grader verdict, exit status, timeout, duration, peak memory and artifact hashes. The report shows a per-task table, a filterable timeline of every event, and the captured stdout and stderr. It can also compare two runs side by side. The HTML needs no server and loads no external JavaScript.

The Virtual Embryo Challenge Agent Team track asks teams to preserve complete trajectories, prompts, harness details, tools, permissions, budgets, and the run that produced the final prediction. Raw agent logs are usually hard to inspect. This repo makes them easier to follow without changing the underlying trace.

It is a viewer, not an evidence certifier.

## How it differs from Trajectory Lens

[Trajectory Lens](https://github.com/xxx12e/vec-community-kit/tree/main/vec_trajectory_lens) reads the native session logs of agent CLIs (Claude Code, Codex CLI and OpenCode). It counts tokens and tool calls by tool, lists the files that file tools wrote or edited, flags network-shaped commands, and scans for and redacts secrets before it writes anything. It does not read the Harness Lab `trace.jsonl`, it has no grader results, and it reports no exit status, timeouts, peak memory or artifact hashes (its sha256 values cover its own input logs). This tool does the opposite: it reads the Harness Lab trace and shows, for each task, the grader verdict together with the exit status, timeout, memory and artifact hashes. Its verdict is PASS only when the grader passed, the agent exited with code 0 and the task did not time out. It also compares two runs. It does not count tokens, flag network access or scan for secrets. The Harness Lab masks secret-looking values only in the command and argument lists it writes, so agent stdout and stderr are copied into the report as they were logged. Check a report before sharing it. A team whose agent runs under Claude Code can use both tools: this one for the harness results, Trajectory Lens for the session log.

## Install

```bash
git clone https://github.com/i-habib/virtual-embryo-community
cd virtual-embryo-community/agent-trace-explorer
pip install -e .
```

This installs the `trace-explorer` command. For tests, use `pip install -e '.[dev]'`.

## Build a report from a Harness Lab run

Run the harness (see [../agent-harness-lab/](../agent-harness-lab/)), then build the report from the trace it wrote:

```bash
vec-agent-bench run --command 'python my_harness.py' --out runs/my-harness
trace-explorer build runs/my-harness/trace.jsonl -o report.html
```

The bundled examples run the same way. They are small hand-written traces that follow [the trace format](../agent-harness-lab/docs/trace-format.md):

```bash
trace-explorer build examples/reference.jsonl -o reference.html
trace-explorer build examples/incomplete.jsonl -o incomplete.html
```

Formats: `auto`, `vec-bench`, `claude`, `generic`. Auto-detection picks `vec-bench` when the file has Harness Lab events. Force a parser when detection is ambiguous:

```bash
trace-explorer build trace.jsonl --format claude -o report.html
```

## Other inputs

**Claude Code stream JSON.** Best-effort parsing of `--output-format stream-json`: assistant text, tool uses, tool results and the final result record.

**Generic JSONL.** For other harnesses, each line is a JSON object. The parser looks for `ts` / `timestamp`, `event` / `type` / `kind`, and `text` / `message` / `content`, and keeps the full object in the report.

```json
{"timestamp":"...","type":"tool","message":"ran scorer","task_id":"t1"}
```

## What the report shows

For a Harness Lab trace:

- a summary card: tasks passed, events, artifacts, summed task time and peak RSS;
- a per-task table: verdict, grader result, return code, timeout, duration, peak RSS and artifact count;
- a timeline of all events, with the grader checks, exit status and each artifact's path, size and SHA-256;
- filters for task, event type and free text.

It can also compare two runs side by side, with per-task verdicts and summary numbers. The comparison reports recorded behavior only. It does not decide which scientific result is better.

## Quick text summary

```bash
trace-explorer summary examples/incomplete.jsonl
```

```text
source: examples/incomplete.jsonl
format: vec-bench
events: 12
tasks: 1/2
tool calls: 0
stderr lines: 1
artifacts: 1
peak RSS: 99.0 MiB
```

Add `--json` for machine-readable output, including `task_grades` and per-task `task_details`.

## Compare runs

```bash
trace-explorer compare examples/reference.jsonl examples/incomplete.jsonl -o comparison.html
```

## Demo

`examples/` holds two small Harness Lab-style traces: `reference.jsonl`, a clean run, and `incomplete.jsonl`, a run with a failed task, stderr, and no artifact for that task. Generate all three HTML reports:

```bash
python examples/build_demo.py
```

## Limits

- It reads logs. It does not show that a run was autonomous, that its configuration was locked, or that the rules were followed.
- It does not scan for secrets or redact anything. Stdout and stderr from the agent appear in the report unchanged.
- Durations and peak RSS are the values the harness measured. The viewer does not check them.
- The whole trace is read into memory and copied into the HTML, so a very large trace gives a large file.

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
