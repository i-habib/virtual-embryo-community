---
name: vec-harness-dryrun
description: Dry-runs the exact agent command that will be locked, on the generated tasks in agent-harness-lab, and reads each result with agent-trace-explorer until the harness passes. Use before locking any Agent Team run, and again after every change to the harness, prompt, model string or tool setup.
---

# Dry-run the harness before the lock

Official rule, rules section 9 (https://virtualembryo.ai/challenge/rules):

> Before the lock, everything is permitted. Write and rewrite the harness, choose and change the model, draft prompts, set budgets, and run the agent as many times as you like.

That permission ends at the lock. Use it to find the faults that would otherwise waste a locked run: lost gene order, broken cell pairing, missing output files and timeouts.

## What the dry run must not use

Never use the real task as the dry run. Use the generated tasks in [agent-harness-lab](../../agent-harness-lab/README.md). A dry run on the real task leaves its outputs and scores in the same place as the locked run. That makes it harder to show that the evidence matches the submitted file. Rules section 9: "Evidence must correspond to the run that produced the submitted file."

## Steps

1. Write the command you will lock as one string. Use the runner's placeholders, for example `'my-agent --prompt {prompt} --model MODEL_STRING'`, or a wrapper that reads `VEC_BENCH_PROMPT`. Keep the model string and every flag identical to the locked run.

2. Run the dry run into a new folder. Do not reuse a folder:

   ```bash
   vec-agent-bench run --command 'my-agent --prompt {prompt} --model MODEL_STRING' --out runs/dryrun-01
   ```

   To fix one task at a time, add `--tasks repair_gene_order,t2_copy_last`. Run the full list before you lock. The task IDs are in `vec_agent_bench/tasks.py`.

3. Build the report and the text summary from the trace:

   ```bash
   trace-explorer build runs/dryrun-01/trace.jsonl -o runs/dryrun-01/report.html
   trace-explorer summary runs/dryrun-01/trace.jsonl
   ```

4. Read each task's verdict. A task passes only if the grader accepts the output, the agent exits with status 0 and the task does not time out. The `task_end` record shows all three. For a failing task, read the `grade` checks, the `agent_exit` record and the `agent_stderr` lines.

5. Fix the harness or the prompt. Do not fix the output file by hand, because a hand-edited file breaks the provenance record in [vec-record-provenance](../vec-record-provenance/SKILL.md). Then start a new dry-run folder and repeat from step 2 until every task passes. If a task cannot pass, write down why and what it means for the real run.

6. Lock only after a dry run of the current configuration has passed. Note the dry-run folder names in the lock notes. Keep dry-run folders outside the locked workspace.

## Limits

- The suite checks plumbing on deterministic, generated data. Passing it does not make a run eligible, and the organisers' checks still apply. The harness README says the same.
- The trace masks secret-looking values in the command line only. Agent stdout and stderr are copied as printed, so check `report.html` for secrets before you share it.
- A dry run that passes shows that the pipeline works. It does not show that the method is good. Use [vec-score-locally](../vec-score-locally/SKILL.md) for that, and only against targets the rules allow.
