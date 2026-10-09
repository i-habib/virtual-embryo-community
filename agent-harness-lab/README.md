# Virtual Embryo Agent Harness Lab

A dry-run benchmark for the Virtual Embryo Challenge Agent Team track.

The Agent Team rules let people develop and test a harness before a run is locked. Once a submitted run starts, the configuration is fixed and the prediction must be produced by the agent without human steering. This repo gives a harness a set of small challenge-specific jobs **before** a locked run.

The tasks are deterministic and use generated data. There is no LLM judge and no leaderboard feedback.

## What it tests

The current suite checks whether an agent setup can:

1. inspect an unfamiliar `.h5ad`;
2. repair gene order without changing expression semantics;
3. repair non-finite / negative expression when explicitly asked;
4. reorder cells without breaking expression-coordinate pairing;
5. produce a valid Task 1-style copy-last file at the full 32,285-gene width (the Task 1 gene count stated on https://virtualembryo.ai/challenge/data);
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

`trace.jsonl` records task starts/ends, stdout/stderr, the agent's exit status, generated artifacts, deterministic grading, wall time, and peak process-tree RSS. Its fields are documented in [`docs/trace-format.md`](docs/trace-format.md). [Agent Trace Explorer](../agent-trace-explorer/) in this repository can turn the file into a filterable HTML timeline or compare two runs.

### Pass and fail

A task passes only if all three hold:

- the grader accepts the output in the task workspace;
- the agent process exits with status 0;
- the agent does not hit `--timeout-seconds`.

`task_end` records `passed`, and also `grader_passed`, `returncode` and `timed_out`, so a grader pass with a failed agent run is visible in the trace.

### Process cleanup

The agent starts in its own process group. On timeout, the runner kills that group, so grandchild processes are killed too. When the agent exits normally, the runner also kills any processes still in the group. Processes that leave the group on purpose (for example with `setsid` or a double fork that changes session) are not caught.

### Secrets in the trace

`run_start.command_template` and `task_start.argv` are written to `trace.jsonl` after redaction. The redactor replaces:

- the value after a flag whose name ends in `key`, `token`, `secret`, `password` or `passwd` (for example `--api-key VALUE`), and the value of `--api-key=VALUE`;
- the value of any `NAME=VALUE` assignment whose name ends in one of those words (for example `OPENAI_API_KEY=...`);
- the token after `Bearer`;
- bare tokens with common prefixes (`sk-`, `ghp_`, `github_pat_`, `hf_`, `xox?-`).

Redacted values appear as `<redacted>`. The command that runs is not changed, and environment variables are never written to the trace. This is pattern matching, not a guarantee. Keep secrets in environment variables or files your harness reads itself, not in the command line. The agent's stdout and stderr are recorded as printed, so a harness that prints a secret will log it.

## Check the benchmark itself

A deterministic reference program is included only to test the benchmark plumbing:

```bash
vec-agent-bench self-test --out runs/reference
```

It should pass every task. It is not an Agent Team baseline and is not presented as autonomous research.

## Why these tasks

The suite is aimed at mistakes that are expensive to discover after a locked run has started: losing gene order, breaking row/coordinate correspondence, writing invalid expression, mishandling a wide sparse matrix, or failing to leave a clear artifact trail.

The rules page is the reference for eligibility and evidence requirements:

- https://virtualembryo.ai/challenge/rules
- https://virtualembryo.ai/challenge/account/submissions (where submissions are made)

The tasks page (https://virtualembryo.ai/challenge/tasks) describes the challenge tasks. It is not authoritative for submission requirements; use the rules page for those. The data page (https://virtualembryo.ai/challenge/data) gives the panel and gene counts for each board.

## What the Agent Team rules ask for

This section paraphrases and quotes section 9 of https://virtualembryo.ai/challenge/rules. The rules page is the reference, and it may change.

On evidence, the rules say:

> Every Agent Team submission must be accompanied by evidence of the run that produced it. A submission is accepted and held, but is not scored and does not appear on any board, until at least two distinct kinds of evidence have been uploaded against it, one of which must be the trajectory.

The kinds are the trajectory, the prompts, and the harness, plus other material needed to follow the run. The rules then say:

> Any two distinct kinds satisfy the minimum; more is better and none is a substitute for another.

These two sentences do not agree. The first requires the trajectory among the two kinds. The second says any two kinds satisfy the minimum. The rules do not resolve this, so a submission with prompts and harness but no trajectory is ambiguous. Upload the trajectory unless the organisers confirm otherwise.

Prizes need more than the minimum. The rules say:

> Agent Team prizes additionally require evidence that the work was the agent's: the trajectory, the prompts, and the harness.

So a prize-eligible entry needs all three kinds. The rules also say that evidence is held privately and is not published.

Each Agent Team submission must also state the framework and the model:

> Every Agent Team submission must also state what ran the agent and on which model: the framework, whether that is a published one or your own, and the model string you actually ran.

These fields are free text and are not judged.

This benchmark's trace is for harness testing. It is not the evidence the Challenge requires, and this repository does not produce that evidence for a submission.

## Tests

```bash
pip install -e '.[dev]'
pytest -q
```

The tests cover the runner's pass/fail rules, process cleanup, secret redaction, a no-op agent that must fail every task, and graders that reject wrong gene order and invalid expression values.

CI is defined at the repository root in [`.github/workflows/agent-harness-lab-ci.yml`](../.github/workflows/agent-harness-lab-ci.yml). It runs the unit tests and the full deterministic self-test on pushes and pull requests that touch this directory.

## License

MIT.
