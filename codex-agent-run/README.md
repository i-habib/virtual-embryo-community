# codex-agent-run

A small standard-library tool that locks, launches and packages one `codex exec` run for the Virtual Embryo Challenge Agent Team track.

The Agent Team rules (challenge site, sections 9 and 14) require that, from the start of a run, the prompts, harness, model, tools and permissions and budget are fixed; that the trajectory and at least one other kind of evidence (prompts or harness) come from that exact run; that predictions are written by the agent; and that the framework and the exact model string are stated. Prizes need the trajectory, the prompts and the harness. This tool produces those files for the OpenAI Codex CLI. It does not decide whether a run complies.

## Commands

Run each command from this directory, or give the script's full path. Requires Python 3.11 or later and a `codex` on PATH (tested against codex-cli 0.162.1 for the lock step only; see Limits).

```
# 1. Lock: snapshot and hash everything, write lock.json. Refuses to overwrite a lock.
python codex_lock.py --out RUNS/run1 --prompt prompt.md --workspace WS --model gpt-6-luna --hours 8 \
    --data-manifest data.json [--sandbox workspace-write] [--approval never] [--reasoning-effort high] \
    [--predictions-dir out/predictions] [--codex-home ~/.codex] [--use-user-config]

# 2. Launch: verify the lock, run `codex exec --json` once with the locked settings, record the run.
python codex_launch.py RUNS/run1

# 3. Package: check the lock and predictions again, write the evidence bundle.
python codex_package.py RUNS/run1 --out BUNDLES/run1 [--team-uploaded-mb 120]
```

`data.json` lists the data files as `{"files": ["/abs/path.h5ad", "dir_or_file_relative_to_this_json"]}`. A directory is expanded to the files under it. Every listed file is hashed at lock time and hashed again at launch and at packaging.

Run directories should sit outside the workspace. The lock directory and the agent's workspace are separate by design; the tool does not police reads inside the sandbox.

## What the lock records

- The prompt file and the workspace `AGENTS.md` (byte copies, SHA-256 and size). The lock refuses a prompt or brief that still contains `{{` placeholders, a credential-shaped string, or the `OPERATOR-ONLY` block.
- The Codex context files that Codex may load: `$CODEX_HOME/AGENTS.override.md`, `$CODEX_HOME/AGENTS.md`, and the workspace `AGENTS.override.md`. Present files are copied and hashed; absent ones are recorded as absent.
- `config.toml`: a SHA-256 of the raw file, plus a redacted copy. Values under keys that look secret, values in `env` or `headers` tables, multi-line strings and any credential-shaped text are replaced with `<redacted>`. The lock lists the MCP servers, enabled plugins and hooks that the config would switch on.
- The exact model string, sandbox, approval policy, reasoning effort, and whether the user config is ignored (the default).
- The `codex` path, binary SHA-256, `codex --version` output and the text of `codex exec --help`. The lock refuses if any flag the tool uses is missing from that help text.
- The wall-clock budget in seconds, the exact argv, the working directory and the environment variables the run sets (`CODEX_HOME`, and whether `OPENAI_API_KEY` is set, never its value).
- The data manifest hashes, the predictions directory (which must be empty at lock time), and copies of the tool's own scripts.

Default choices: the user config is ignored, so the notify hook and enabled plugins in a personal `config.toml` do not run during the agent's session. Pass `--use-user-config` to keep it; the lock then lists what it enables. The prompt reaches Codex on stdin from the locked copy, and stdin then reaches end of file, so the run has no terminal input. Danger-full-access is not accepted.

## What the launch does

Launch refuses if `lock.json` no longer matches `lock.sha256`, or if any locked input, data file, script or the codex binary differs from the lock. It writes `launch_state.json` as `running` before starting Codex, so a run is launched once. It starts `codex exec --json` in its own process group, copies stdout byte for byte into `trajectory.jsonl`, copies stderr into `stderr.log`, and at the budget sends SIGTERM then SIGKILL to the group (exit code 124). It then finds the session file under `$CODEX_HOME/sessions` by session id from the stream, or by modification time if the id is not found, copies it unchanged into `trajectory/rollout/`, snapshots the prediction directory, and records the start and end times, exit code, signal, timeout flag and inputs changed during the run.

## What the bundle contains

`BUNDLEDIR` receives:

| file | contents |
|---|---|
| `trajectory.zip` | `stream.jsonl` (the stdout byte copy), `stderr.log`, `last_message.txt`, every session file copied, `summary.json` (event counts, turns, usage, models named in the stream) |
| `prompts.zip` | the initial prompt, the workspace `AGENTS.md`, and each Codex context file present at lock time |
| `harness.zip` | the four scripts, `lock.json`, `lock.sha256`, the redacted config snapshot, the exec help and version text, `launch_state.json`, `predictions_at_end.json` |
| `evidence_manifest.json` | framework and version, model string, sandbox, budget, timing, exit code, lock hash, the size and SHA-256 of every archive and every member, the stream summary, warnings, and the team cap arithmetic |
| `README.md` | a plain statement of the framework and model string for the submission, the run facts, the file table, the checks performed, and the warnings |

Prediction files are not copied. Their names, sizes and SHA-256 values go into the manifest, so the upload uses the unchanged files from the workspace.

Packaging refuses, and writes nothing, when: the lock or a locked input changed; the run did not finish; the prediction directory differs from the snapshot taken at run end (added, removed or changed files are named); there are no predictions (unless `--allow-empty`); any packaged file matches a credential pattern (only the pattern names are printed); a file or zip is over 200,000,000 bytes (the rules' per-file cap in section 9, read as the smaller of the two readings of "200 MB"); or a prediction is over 1200 MB (section 11). A file over the cap is not truncated. The message asks you to file it in full and summarise it, or split it. The per-team 600 MB cap cannot be known locally; pass your own uploaded total with `--team-uploaded-mb` and the tool warns when this bundle would pass 600 MB.

## Tests

```
python -m pytest -q
```

The tests put a fake `codex` executable first on PATH. It answers `--version` and `exec --help`, reads the prompt from stdin, prints `--json`-style events, writes a session file and a prediction file, and can be made to sleep, fail or leak a credential. No model is called. The tests cover refusals (overwrite, placeholders, credentials, operator block, leftover predictions, full access), redaction, a full lock-launch-package run, tampering with the lock, the prompt or the brief, edits to predictions after the run, the budget kill, a credential in the stream, and the size cap.

## Limits

- Codex's own sandbox (`--sandbox workspace-write` by default) is the only enforcement layer. The tool adds no network policy, no file policy and no command filter. A run can read whatever the sandbox lets it read, which can include other run directories on the same machine.
- The bundle documents; it does not attest. The hashes show what changed after the lock and what did not. They cannot prove that no person intervened between the lock and the start of the run, and they cannot prove that the agent followed the rules. The organisers' audit decides that.
- The lock step was run against the installed codex-cli 0.162.1 and its help text matched. The launch and packaging paths were tested only against the fake codex. The event names used for the stream summary follow the Codex non-interactive documentation as read by the vec-community-kit authors; they were not checked against this Codex version. Session files on this machine are named `rollout-*.jsonl.zst`. The tool copies them byte for byte and does not decompress them, so the summary does not read them.
- The stream summary and the model check read only the stream. The model string is recorded as locked; it is not verified against the session file.
- The lock stores a SHA-256 of the raw `config.toml`, not the file itself. Anyone with the original file can check it. The redacted copy is the only config text in the evidence.
- The tool records the Codex context files at lock time. It does not scan the workspace or its git history for prior scores or steering notes. That audit is a separate step (`../agent-prelock-audit/`, which is being built in parallel and is not present yet).
- The tool runs on POSIX systems only (it uses process groups). It is not tested on Windows.
- The rules allow a crashed run to be restarted with an unchanged configuration, and count it as the same run. This tool does not support that. A run that crashes stays at `status: running`, cannot be packaged or relaunched, and a new attempt needs a new lock, which makes it a new run.
- Codex may write its own state into `$CODEX_HOME` during a run. If `config.toml` or a context file changes during the run, packaging refuses and the message names the file.

## Files

- `codex_common.py`: hashing, redaction, credential patterns, lock verification, session id parsing.
- `codex_lock.py`, `codex_launch.py`, `codex_package.py`: the three commands.
- `AGENTS.template.md`: a task brief for the agent with placeholders, and an operator checklist between `BEGIN OPERATOR-ONLY` and `END OPERATOR-ONLY`. Delete that block before locking.
- `tests/test_codex_run.py`: the test suite described above.

Credit: the Claude Code path of `vec_agent_evidence` in xxx12e's vec-community-kit already provides a lock, launcher and package, and its `codex-package` packages a finished Codex run after the fact, which this tool extends with a Codex lock and launcher while using the same evidence kinds and the same 200 MB per-file cap.
