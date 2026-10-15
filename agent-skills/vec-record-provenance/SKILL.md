---
name: vec-record-provenance
description: Records and packages the evidence for a Virtual Embryo Agent Team run, covering the exact prompt, harness command, model string, framework, data file hashes, run log, and the trajectory, prompts and harness archives. Use before starting any agent run that will be submitted, and again after the run ends and before any upload.
---

# Record provenance for an Agent Team run

Official rule, rules section 9 (https://virtualembryo.ai/challenge/rules):

> "Evidence must correspond to the run that produced the submitted file. Evidence from a different run, edited to fit, or reconstructed after the fact is a misrepresentation."

Treat every finished run as read-only. Do not edit its prompt, logs, configuration or predictions after the run ends. If a file is wrong, say so in the report and start a new locked run.

## Before the run

1. Save the starting prompt as a file, for example `runs/RUN_ID/prompt.md`. A person may write the starting prompt. Nobody may read intermediate results and steer the agent from them. Changes to the prompt or harness are allowed only before the lock.
2. Record the values the rules ask for (rules section 9): the framework (a published one or your own), and the exact model string you run. Record the CLI version too, for example `claude --version`.
3. Hash every input data file, and keep the output with the run:

   ```bash
   shasum -a 256 data/*.h5ad > runs/RUN_ID/data_hashes.txt
   ```

4. Before a locked run, check the harness on the dry-run tasks in [agent-harness-lab](../../agent-harness-lab/README.md).

## Lock and run

Use the Claude Code path of `vec_agent_evidence` in the community kit (https://github.com/xxx12e/vec-community-kit, folder `vec_agent_evidence`). It hashes the prompt, settings, model, tool policy, data files and CLI binary before the run, then runs the agent with a wall-clock limit and collects the transcript:

```bash
python -m vec_agent_evidence run --task T3 --prompt runs/RUN_ID/prompt.md --model MODEL_STRING --data-root ./data --hours 8
```

Keep the complete stdout and stderr. The kit writes the stream JSON from `claude -p --output-format stream-json`.

For a Codex run, use [codex-agent-run](../../codex-agent-run/README.md): `codex_lock.py` before the run, `codex_launch.py` to run it, `codex_package.py` to build the bundle. The kit's `codex-package` command can also pack a finished `codex exec --json` run after the fact.

For a Harness Lab run, `trace-explorer build runs/RUN_ID/trace.jsonl -o report.html` makes a static report from the trace. See [agent-trace-explorer](../../agent-trace-explorer/README.md). The report is a viewer, not a certificate. Check it for secrets before sharing, because agent stdout is copied into it as logged.

## Package

```bash
python -m vec_agent_evidence package --run-dir runs/RUN_ID
```

This writes the trajectory, prompts and harness archives. Rules section 9 caps each file at 200 MB and the team total at 600 MB. A trace too large for the cap should be filed in full and summarised. Do not truncate it silently.

## Before any upload

- Confirm that each submitted file's hash matches the prediction in the run record. The packager refuses a package whose prediction bytes differ from the finalized ones, and an edited file is not an Agent Team entry (rules section 9).
- Search the evidence folder for credential-shaped strings, such as `api_key`, `token` or `Bearer`. The kit scans for these, and the search is a second check.
- Keep your own copy of every upload with its checksum (rules section 12: "Keep your own copy of everything you submit").
- Ask the user to approve each upload in chat. Uploads cannot be undone, and approval for one upload does not cover the next.

## Reference

- Official rules, section 9 (Agent Team entries): https://virtualembryo.ai/challenge/rules
- Evidence kit and its README: https://github.com/xxx12e/vec-community-kit
