# Virtual Embryo Agent Harness Lab

A dry-run benchmark for the Virtual Embryo Challenge Agent Team track.

The Agent Team rules let people develop and test a harness before a run is locked. Once a submitted run starts, the configuration is fixed and the prediction must be produced by the agent without human steering. This repo gives a harness a set of small challenge-specific jobs **before** a serious locked run.

The tasks are deterministic and use generated data. There is no LLM judge and no leaderboard feedback.

## What it tests

The current suite checks whether an agent setup can:

1. inspect an unfamiliar `.h5ad`;
2. repair gene order without changing expression semantics;
3. repair non-finite / negative expression when explicitly asked;
4. reorder cells without breaking expression-coordinate pairing;
5. produce a valid Task 1-style copy-last file at the full 32,285-gene width;
6. preserve expression and 3D coordinates for a Task 2-style copy-last file;
7. produce a Task 3-style wild-type identity prediction;
8. interpret a few deliberately simple scorer/validator failure patterns;
9. record file hashes for artifact lineage.

These are workflow probes, not a model benchmark. The graders are public and deterministic on purpose. Passing them does not certify Agent Team eligibility and does not replace the official task validator.

## Run your harness

Install:

```bash
git clone https://github.com/i-habib/virtual-embryo-community
cd virtual-embryo-community/agent-harness-lab
pip install -e .
```

List tasks:

```bash
vec-agent-bench list
```

The runner executes your command once per task with the task workspace as its current directory. It exposes:

```text
VEC_BENCH_TASK_ID
VEC_BENCH_WORKSPACE
VEC_BENCH_PROMPT_FILE
VEC_BENCH_PROMPT
```

You can also use exact command placeholders `{prompt}`, `{prompt_file}`, `{workspace}`, and `{task_id}`.

For a CLI that accepts the prompt as an argument:

```bash
vec-agent-bench run \
  --command 'my-agent --prompt {prompt}' \
  --out runs/my-harness
```

For a wrapper that reads `VEC_BENCH_PROMPT` from the environment:

```bash
vec-agent-bench run \
  --command 'python my_harness.py' \
  --out runs/my-harness
```

Run a subset:

```bash
vec-agent-bench run \
  --command 'python my_harness.py' \
  --tasks inspect_h5ad,repair_gene_order,t2_copy_last \
  --out runs/smoke
```

Each run writes:

```text
runs/my-harness/
  trace.jsonl
  summary.json
  tasks/
    inspect_h5ad/
    ...
```

`trace.jsonl` records task starts/ends, stdout/stderr, generated artifacts, deterministic grading, wall time, and peak process-tree RSS. Its fields are documented in [`docs/trace-format.md`](docs/trace-format.md). [Agent Trace Explorer](https://github.com/i-habib/agent-trace-explorer) can turn the file into a filterable HTML timeline or compare two runs.

## Check the benchmark itself

A deterministic reference program is included only to test the benchmark plumbing:

```bash
vec-agent-bench self-test --out runs/reference
```

It should pass every task. It is not an Agent Team baseline and is not presented as autonomous research.

## Why these tasks

The suite is aimed at mistakes that are expensive to discover after a locked run has started: losing gene order, breaking row/coordinate correspondence, writing invalid expression, mishandling a wide sparse matrix, or failing to leave a clear artifact trail.

The official Challenge pages remain authoritative for current rules and submission requirements:

- https://virtualembryo.ai/challenge/rules
- https://virtualembryo.ai/challenge/account/submissions
- https://virtualembryo.ai/challenge/tasks

The current rules also require Agent Team evidence from the exact run that produced the submitted prediction. This benchmark's trace is for harness testing; it is **not** a replacement for the evidence required by the Challenge.

## Tests

```bash
pip install -e '.[dev]'
pytest -q
```

CI runs the unit tests and the full deterministic self-test.

## License

MIT.
