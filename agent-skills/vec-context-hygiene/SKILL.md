---
name: vec-context-hygiene
description: Keeps human steering material out of a locked Agent Team run by auditing the agent's context files, disabling auto memory, starting from a clean workspace and recording the context file hashes in the lock. Use after the last dry run and before any locked Agent Team run starts.
---

# Keep steering material out of the run

Official rule, rules section 8 (https://virtualembryo.ai/challenge/rules):

> Agent Team: the method is developed by an autonomous agent. A person may write the starting prompt, but nobody may read intermediate results and steer the agent on the strength of them.

The agent must not be able to read the notes, scores or held-out files that a person would use to steer it. This skill covers what the agent can read. The audit checks for that, and it does not prove that no person steered the run.

## Steps

1. Build a clean workspace. Copy only the files the lock lists into an empty directory, then run `git init` there. Do not run the agent inside the team repository. Its git history holds past scores and notes, and the agent could read them with `git log`.

2. Run the pre-lock audit on that workspace, if the folder is present:

   ```bash
   python agent-prelock-audit/prelock_audit.py   # see ../../agent-prelock-audit/README.md
   --workspace WS --cli claude --out LOCKDIR
   ```

   See [agent-prelock-audit](../../agent-prelock-audit/README.md). It writes `prelock_lock.json`, which lists each context file the CLI loads (with size and SHA-256), and `prelock_report.md`. It exits with status 1 when any BLOCK finding exists. The audit also scans the workspace, the git history, the auto memory folder, the CLI's session logs and any path given with `--extra-scan`. Fix each BLOCK finding by changing the workspace or the environment, then run the audit again. Do not clear a finding by editing the report.

   If the audit folder is missing, do steps 3 to 5 by hand and list what you checked in the lock notes.

3. Turn off auto memory for the run. For Claude Code, set `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in the environment the agent starts in. For Codex, set `CODEX_HOME` to a folder that holds only the locked context files, and do not pass `--use-user-config` to `codex_lock.py`.

4. Keep steering material outside what the agent can open. Move leaderboard logs, notes with scores, team memory files and any held-out file out of the workspace and off the agent's paths. The Codex runner's README warns that the sandbox is the only enforcement layer, and that a run "can read whatever the sandbox lets it read, which can include other run directories on the same machine." Rules section 10: "Attempting to recover held-out labels, probe the evaluation infrastructure, or otherwise circumvent fair evaluation is prohibited and is grounds for disqualification."

5. Record the hashes in the lock. Hash each context file and the prompt, and keep the list in the lock folder with `prelock_lock.json`:

   ```bash
   shasum -a 256 WS/CLAUDE.md WS/AGENTS.md PROMPT.md > LOCKDIR/context_hashes.txt
   ```

   Check the hashes again at launch. A changed file means the configuration moved. Rules section 9: "Pausing a locked run to change its configuration ends that run."

6. Lock, then leave the workspace alone. Do not open the agent's notes or intermediate outputs during the run, and do not edit the workspace until the run ends. Rules section 9: "A person may not read the agent's intermediate results (scores, diagnostics, partial outputs) and steer the next step on the strength of them."

## Limits

- A clean audit means the audit found no signal. It does not show that no person steered the run. Use the evidence from [vec-record-provenance](../vec-record-provenance/SKILL.md) for that, and the organisers' audit decides the rest.
- The audit sees files on this machine only. Any memory the CLI keeps elsewhere needs its own check before the lock.
- Run the audit again if the context files change after it ran. A stale report proves nothing about the current files.
