---
name: vec-budget-guard
description: Tracks the wall clock and compute budget declared in a locked Agent Team run, writes checkpoints, and makes the agent stop cleanly with its best valid prediction before the budget ends. Use when writing the stop rule for a locked run, when rehearsing it with a short budget, and when a launched run is close to its limit.
---

# Stop a locked run before its budget ends

Official rule, rules section 9 (https://virtualembryo.ai/challenge/rules): the budget is part of the configuration lock. "The prompts, the harness, the model, the tools and permissions available to the agent, and the budget are fixed as the run begins." Changing the budget or the stop rule after the lock ends the run.

A run that the launcher stops at its limit is recorded as timed out. The Codex launcher sends SIGTERM to the process group at the budget and kills it after 30 seconds if it does not exit. The packager keeps a timed-out run with a warning. Write the stop rule so the agent finishes first.

## Before the lock

1. Declare the budget in the lock. The Codex lock takes `--hours` and records wall-clock seconds, and `vec_agent_evidence` takes `--hours` too. The Codex lock records no compute cap. If the team declares a token or GPU-hour cap, write it into the prompt as a rule, and have the harness count it and write it to each checkpoint.

2. Write the stop rule into the prompt or harness. A typical rule: at 90 percent of the wall-clock limit, the agent starts finalising. Leave room for the slowest format check and the file write.

3. Name the selection rule for "best valid prediction" before the lock. Rules section 9: "Within a locked run, the agent evaluates and selects its own final output." The rule must come from the lock. If the rule is "the latest checkpoint that passes the format check", say so. Do not leave the choice to the person who reads the result.

4. Rehearse with a short budget in a dry run from [vec-harness-dryrun](../vec-harness-dryrun/SKILL.md), for example `--hours 0.25` in `codex_lock.py`. Check that the agent writes its final prediction, exits with status 0 and is not marked timed out.

## During the run

5. Write a checkpoint at each milestone. Each checkpoint holds the elapsed seconds, the file names, the SHA-256 of each prediction and the result of the format check:

   ```bash
   python test-phase-switchover/check_test_contract.py PRED.h5ad BOARD_KEY --index panels/index.json --panels-dir panels
   ```

   Exit code 0 is a pass, 1 is a failure, and 2 is a usage or read error. If the sandbox has no network, store `index.json` and the panel file with the lock, and pass them with those two options. Rules section 11: "Format checks are unlimited in every phase and spend nothing."

6. At the stop point, the agent does three things, in order. It stops starting new work. It selects the newest checkpoint that passed the format check, using the lock's selection rule. It records that file's name and SHA-256 in the final report, and it does not rewrite the file. If no checkpoint passed, it writes the fallback the lock names and says so in the report.

7. Do not read checkpoint scores during the run, and do not change the budget or the stop point. Rules section 9: "A person may not read the agent's intermediate results (scores, diagnostics, partial outputs) and steer the next step on the strength of them, may not change the configuration mid-run, and may not choose among the run's own intermediate outputs on the agent's behalf."

## Limits

- The stop rule cannot interrupt a single long command. Keep each tool call shorter than the margin between the stop point and the budget, and set the margin from the longest step you run.
- A checkpoint that passed the format check is not a good prediction. The format check reports well-formedness only.
- After the run, check the trace with [agent-trace-explorer](../../agent-trace-explorer/README.md). A run marked timed out is a run that did not finish under its own rule, and the report should say so.
