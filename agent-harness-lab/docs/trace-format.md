# Harness Lab trace format

Each `vec-agent-bench run` writes newline-delimited JSON to `trace.jsonl`.

Every record has:

```json
{"ts":"2026-10-01T00:00:00Z","event":"..."}
```

Records may additionally carry a `task_id` and event-specific fields.

## Events

`run_start`

```json
{"event":"run_start","benchmark_version":"0.1.0","command_template":"...","tasks":["inspect_h5ad"]}
```

`task_start`

```json
{"event":"task_start","task_id":"inspect_h5ad","title":"...","argv":["..."]}
```

`agent_stdout` / `agent_stderr`

```json
{"event":"agent_stdout","task_id":"inspect_h5ad","text":"..."}
```

`artifact`

```json
{"event":"artifact","task_id":"inspect_h5ad","path":"answer.json","size_bytes":80,"sha256":"..."}
```

`grade`

```json
{"event":"grade","task_id":"inspect_h5ad","passed":true,"checks":["..."]}
```

`task_end`

```json
{"event":"task_end","task_id":"inspect_h5ad","passed":true,"returncode":0,"timed_out":false,"duration_seconds":1.2,"peak_rss_mb":120.4,"checks":["..."]}
```

`run_end`

```json
{"event":"run_end","tasks_passed":9,"tasks_total":9}
```

The format is intentionally simple JSONL so other viewers can consume it. [Agent Trace Explorer](../../agent-trace-explorer/) supports it directly.
