# prelock_audit

A pre-lock contamination audit for a Virtual Embryo Agent Team run. Given a workspace and the agent CLI that will run in it, it lists the context files that CLI loads automatically, scans the workspace and those files for steering material and held-out leaks, and writes a lock record for the evidence bundle. It is one Python file with the standard library only.

## Why this matters

The Agent Team track depends on one moment: the configuration lock. The challenge rules (fetched with `curl -sL https://virtualembryo.ai/challenge/rules` on 2026-10-14) say:

- "A person may write the starting prompt, but nobody may read intermediate results and steer the agent on the strength of them."
- "the prompts, the harness, the model, the tools and permissions available to the agent, and the budget are fixed as the run begins"
- "A person may not read the agent's intermediate results (scores, diagnostics, partial outputs) and steer the next step on the strength of them"
- "Returned scores may be used to choose among predictions, not to compute them."
- "No measured data from a held-out stage or genotype may be used, by any route"

A human-track pipeline converted to an agent run often leaves human-derived material where the agent can read it. Examples are a global `CLAUDE.md` or `AGENTS.md` with board numbers, an auto memory index that records past scores, a leaderboard log in the repository, or a cached validation target. The agent then starts with information the rules forbid, and no later step can remove it from the run. This audit runs before the lock so that those files are found and moved while everything is still permitted.

## What it checks

1. **Context inventory.** The files the chosen CLI loads at launch or on demand, with size and SHA-256. Rules, per CLI:
   - Claude Code ([memory docs](https://code.claude.com/docs/en/memory)): `CLAUDE.md`, `CLAUDE.local.md` and `.claude/CLAUDE.md` in the working directory and its ancestors; `~/.claude/CLAUDE.md` and `~/.claude/rules/`; `.claude/rules/` files; `AGENTS.md` only when no `CLAUDE.md` exists in the working directory or above; `@path.md` imports (up to four hops); auto memory in `~/.claude/projects/<key>/memory/`, where the key is the git root path with separators replaced by hyphens. `autoMemoryEnabled`, `autoMemoryDirectory` and `CLAUDE_CODE_DISABLE_AUTO_MEMORY` are honoured.
   - Codex ([AGENTS.md docs](https://learn.chatgpt.com/docs/agent-configuration/agents-md)): the first non-empty of `AGENTS.override.md` or `AGENTS.md` in `CODEX_HOME` (default `~/.codex`), then one file per directory from the project root down to the working directory.
   - OpenCode ([rules docs](https://opencode.ai/docs/rules/)): project `AGENTS.md` and global `~/.config/opencode/AGENTS.md`, with `CLAUDE.md` and `~/.claude/CLAUDE.md` as fallbacks when no `AGENTS.md` exists. `OPENCODE_DISABLE_CLAUDE_CODE` and `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT` are honoured.
   - `generic` treats every candidate from the three rules above plus `GEMINI.md` as loaded.
2. **Steering and leak scan** of the workspace, the loaded context, the auto memory directory, the git history (file names only) and any `--extra-scan` paths. Session stores that a resume command can reopen (Claude project transcripts, Codex history) are scanned as REVIEW.
3. **Lock record and report.** `prelock_lock.json` holds the context files, hashes, findings, timestamp, CLI and exit code. `prelock_report.md` is the same content as tables.

### Verdicts

| Verdict | Meaning |
|---|---|
| BLOCK | Held-out data or scores inside auto-loaded context. Remove them and rerun before locking. |
| REVIEW | Scores, notes, held-out names, answer files or secret-like values the agent can read with its tools. A person decides and records the decision. |
| INFO | Presence facts that need no action under the rules, such as an auto memory directory that is disabled or shell history that is not scanned. |

The rules that produce BLOCK are: a decimal number on a line with a board, score, leaderboard, skill, headline or submission word; a held-out stage (E7.5, E7.75, E8.5, E8.75, E10.5, E12.5) or a Gata4 or beta-catenin knockout on a line with a number or score word; and a held-out file name in auto-loaded context. Secret-like values are always REVIEW, and their values are never printed or stored. The `.env` assignments are reported by key name only.

## How to run

```sh
python prelock_audit.py \
  --workspace /path/to/agent/workspace \
  --cli claude \
  --out /path/to/evidence/prelock-2026-12-01 \
  --extra-scan ~/.zsh_history
```

Options:

- `--cli claude|codex|opencode|generic` (required).
- `--out DIR` (required). Receives `prelock_lock.json` and `prelock_report.md`. If it is inside the workspace, the audit warns and excludes it from the scan, but the agent could still read it, so keep it outside.
- `--extra-scan PATH` (repeatable). A file or directory the agent can read, such as shell history.
- `--memory-dir DIR`. Use this if the CLI keys auto memory differently from the derived name.
- `--redact-excerpts`. Leaves excerpts out of both outputs. Paths and counts remain.
- `--no-git`. Skips the git history check.
- `--home DIR`. Uses another home directory. Intended for synthetic runs and tests. Without it, `CLAUDE_CONFIG_DIR`, `CODEX_HOME` and `XDG_CONFIG_HOME` are honoured.

Exit codes: 0 when there is no BLOCK, 1 when there is a BLOCK, 2 for a bad workspace path or argument.

Tests use synthetic temporary directories only:

```sh
cd virtual-embryo-community/agent-prelock-audit
python -m pytest -q
```

The lock record and the report contain absolute paths and short excerpts from the scanned files. Treat them as sensitive. Use `--redact-excerpts` when they will be shared.

## Example output

The workspace below is synthetic. Its `CLAUDE.md` imports `notes/status.md`, its auto memory index has a score line, `data/E8.5_truth.csv` is a held-out name, `.env` holds an API key, and the git history contains a removed `leaderboard.csv`. The numbers are invented for the example.

```
$ python3 prelock_audit.py --workspace /tmp/prelock-demo/workspace --cli claude \
    --out /tmp/prelock-demo/out --home /tmp/prelock-demo/home
prelock_audit: cli=claude overall=BLOCK exit=1
  BLOCK 2  REVIEW 6  INFO 1
  lock record: /tmp/prelock-demo/out/prelock_lock.json
  report:      /tmp/prelock-demo/out/prelock_report.md
```

Abridged from `prelock_report.md`:

```
### BLOCK
| Location | Category | Detail | Excerpt |
| .../memory/MEMORY.md:2 | score-like number | decimal number on a line with a board or score word | - heart: Heart interp best 68.45 on the board, keep the same settings. |
| .../workspace/notes/status.md:2 | score-like number | decimal number on a line with a board or score word | Last week the leaderboard score was 74.9 on the board. |

### REVIEW
| .../workspace/.env:1 | secret-like value | environment assignment OPENAI_API_KEY present (value not shown) | OPENAI_API_KEY=[value withheld] |
| .../workspace/data/E8.5_truth.csv | held-out marker in file name | file name carries a held-out stage or knockout marker | E8.5_truth.csv |
| .../workspace/data/E8.5_truth.csv | answer or cached target file name | data file name suggests validation answers or cached targets | E8.5_truth.csv |
| git:9c838215:leaderboard.csv | score or submission file name | git history 9c838215: file name suggests leaderboard, submissions or scores | leaderboard.csv |
| git:f2d40651:data/E8.5_truth.csv | held-out marker in file name | git history f2d40651: file name carries a held-out stage or knockout marker | E8.5_truth.csv |
| git:f2d40651:data/E8.5_truth.csv | answer or cached target file name | git history f2d40651: data file name suggests validation answers or cached targets | E8.5_truth.csv |

### INFO
| .../home/.claude/projects | other project directories under the CLI home | 1 other project directory name(s); not loaded here, readable by the Read tool unless denied; names only, not scanned | |
```

Running the same workspace with `--cli codex` exits 0. Codex does not load `CLAUDE.md`, so the BLOCK lines become REVIEW lines, which is the expected difference between the CLIs.

## How to fix findings

- **BLOCK in a loaded instruction file or memory file.** Move the content out of the workspace, or delete it. For an import, remove the `@` line as well as the target. Then rerun the audit, because the hashes change.
- **Auto memory.** Disable it for the run with `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` or `"autoMemoryEnabled": false` in the project settings. Alternatively, point `autoMemoryDirectory` at an empty directory. A disabled memory directory stays readable with the Read tool, so also deny reads of `~/.claude` in the launcher, as the vec_agent_evidence kit does.
- **Held-out files in the workspace.** Remove them from the working tree, the git history (for example by building a fresh repository from the starting commit), and any cache. A file name is a signal, not a proof of content, so check the file before deciding.
- **Session transcripts and history.** Do not resume an earlier session. Use a fresh launch so that the prior transcript is not loaded.
- **Secret-like values.** Remove them from the workspace, and rotate any key that was live. The audit does not say whether a key is live.
- **Clean worktree.** The most reliable fix is a new worktree or clone that contains only the starting prompt, the harness and the data the rules allow. Run the audit against that directory and launch the agent from it.

## Limits

The report lists these in full. The main ones:

- Pattern rules give false positives and misses. A clean result shows only that the rules found nothing.
- The nearness test for external data (a dataset closer to a held-out stage than to the nearest released stage) is not implemented.
- Codex `config.toml` is not parsed, so custom fallback file names and size limits are not applied.
- Git history is checked by file name only.
- The script does not launch the agent and enforces nothing. Enforcement comes from the launcher and the workspace.
- A lock record shows what was present and what the CLI was expected to load. It does not prove what the agent later read.

## How it complements vec_agent_evidence

The vec_agent_evidence kit in xxx12e/vec-community-kit already denies `~/.claude` reads and disables auto memory at runtime, which covers the agent's reads once it has started, whereas this audit runs before the lock and records what the CLI will load and what the workspace, git history and session logs already contain, which runtime deny rules do not show.
