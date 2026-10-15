#!/usr/bin/env python3
"""Freeze a Codex CLI run before it starts.

Records and hashes: the task prompt, the workspace AGENTS.md brief, the Codex context files
(global and workspace AGENTS files), a redacted copy of config.toml, the exact model string,
sandbox and approval policy, the codex version and binary, the data files listed in a
manifest, the wall-clock budget and this tool's own scripts. Writes lock.json and lock.sha256
into a new run directory. A lock is never overwritten.

Usage:
  codex_lock.py --out RUNDIR --prompt PROMPT.md --workspace WS --model MODEL --hours H
      [--sandbox workspace-write|read-only] [--approval never|on-request|on-failure|untrusted]
      [--reasoning-effort high] [--data-manifest data.json] [--predictions-dir out]
      [--codex-home DIR] [--codex-bin codex] [--use-user-config]

The data manifest is JSON: {"files": ["/abs/file.h5ad", "rel/to/manifest.h5ad", {"path": "...", "role": "..."}]}
A directory entry is expanded to every file under it. Danger-full-access is not accepted.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from codex_common import (
    APPROVAL_POLICIES, HARNESS_FILES, MODEL_RE, REASONING_EFFORTS, REQUIRED_EXEC_FLAGS,
    SANDBOX_MODES, SCHEMA, ToolError, config_summary, credential_hashes, credential_reason,
    load_json, new_run_id, redact_toml, run_text, safe_rel, scan_bytes, sha256_bytes,
    sha256_file, utc_now, write_new,
)

HERE = Path(__file__).resolve().parent


def _checked(path: Path, what: str, forbidden: frozenset, placeholders: bool = True) -> bytes:
    if not path.is_file():
        raise ToolError(f"{what} not found: {path}")
    reason = credential_reason(path, forbidden)
    if reason:
        raise ToolError(f"{what} refused ({path}): {reason}")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"{what} is not UTF-8 text: {path}") from exc
    if placeholders and "{{" in text:
        raise ToolError(f"{what} still has an unrendered placeholder ('{{{{'); fill it in before locking")
    hits = scan_bytes(data)
    if hits:
        raise ToolError(f"{what} contains credential-shaped text ({', '.join(hits)}); remove it before locking")
    return data


def _input_record(role: str, source: Path, data: bytes, run_copy: str) -> dict:
    return {"role": role, "source": str(source), "present": True, "bytes": len(data),
            "sha256": sha256_bytes(data), "run_copy": run_copy}


def load_data_manifest(manifest: Path, forbidden: frozenset) -> list[dict]:
    obj = load_json(manifest)
    entries = obj.get("files") if isinstance(obj, dict) else obj
    if not isinstance(entries, list):
        raise ToolError("data manifest must be a list or {\"files\": [...]}")
    files: list[Path] = []
    for entry in entries:
        if isinstance(entry, str):
            raw = entry
        elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
            raw = entry["path"]
        else:
            raise ToolError(f"bad data manifest entry: {entry!r}")
        p = Path(raw)
        if not p.is_absolute():
            p = manifest.parent / p
        p = p.resolve()
        if p.is_dir():
            files.extend(sorted(q for q in p.rglob("*") if q.is_file()))
        elif p.is_file():
            files.append(p)
        else:
            raise ToolError(f"data file in manifest not found: {p}")
    seen: set[Path] = set()
    rows = []
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        reason = credential_reason(f, forbidden)
        if reason:
            raise ToolError(f"data file refused ({f}): {reason}")
        rows.append({"path": str(f), "bytes": f.stat().st_size, "sha256": sha256_file(f)})
    if not rows:
        raise ToolError("data manifest lists no files")
    return rows


def build_exec_args(workspace: Path, model: str, sandbox: str, approval: str,
                    reasoning_effort: str | None, ignore_user_config: bool,
                    last_message: Path) -> list[str]:
    args = ["exec", "--json", "--color", "never",
            "--model", model,
            "--sandbox", sandbox,
            "--cd", str(workspace),
            "--skip-git-repo-check",
            "-c", f'approval_policy="{approval}"',
            "--output-last-message", str(last_message)]
    if ignore_user_config:
        args.append("--ignore-user-config")
    if reasoning_effort:
        args += ["-c", f'model_reasoning_effort="{reasoning_effort}"']
    args.append("-")  # the prompt is read from stdin; launch feeds the locked copy of the prompt
    return args


def _lock(a: argparse.Namespace) -> int:
    out = a.out.resolve()
    if (out / "lock.json").exists():
        raise ToolError(f"{out}/lock.json already exists; a lock is never overwritten, use a new run directory")
    if out.exists() and any(out.iterdir()):
        raise ToolError(f"{out} exists and is not empty")
    if not (0 < a.hours <= 240):
        raise ToolError("--hours must be greater than 0 and at most 240")
    if not MODEL_RE.fullmatch(a.model):
        raise ToolError("model string has characters outside [A-Za-z0-9._:/-]; pass the exact string")
    ws = a.workspace.resolve()
    if not ws.is_dir():
        raise ToolError(f"workspace is not a directory: {ws}")
    codex_home = (a.codex_home or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")).expanduser().resolve()
    forbidden = credential_hashes(codex_home)

    pred_rel = safe_rel(a.predictions_dir)
    pred_dir = ws / pred_rel
    if pred_dir.exists() and any(pred_dir.iterdir()):
        raise ToolError(f"{pred_dir} is not empty; predictions from an earlier run must not be present at lock time")

    codex_path = shutil.which(a.codex_bin)
    if not codex_path:
        raise ToolError(f"codex binary {a.codex_bin!r} not found on PATH")
    codex_path = str(Path(codex_path).absolute())
    version = run_text([codex_path, "--version"]).strip()
    help_text = run_text([codex_path, "exec", "--help"])
    missing = [f for f in REQUIRED_EXEC_FLAGS if f not in help_text]
    if missing:
        raise ToolError(f"this codex does not list {', '.join(missing)} under `codex exec --help`")

    prompt_src = a.prompt.resolve()
    prompt = _checked(prompt_src, "prompt", forbidden)
    brief_src = ws / "AGENTS.md"
    brief = _checked(brief_src, "workspace AGENTS.md", forbidden)
    if b"OPERATOR-ONLY" in brief:
        raise ToolError("the brief still contains the OPERATOR-ONLY block; delete it before locking")

    inputs = [
        _input_record("prompt", prompt_src, prompt, "inputs/prompt.md"),
        _input_record("workspace_agents", brief_src, brief, "inputs/AGENTS.md"),
    ]
    context_copies: dict[str, bytes] = {}
    for role, src in (("codex_home_agents_override", codex_home / "AGENTS.override.md"),
                      ("codex_home_agents", codex_home / "AGENTS.md"),
                      ("workspace_agents_override", ws / "AGENTS.override.md")):
        if src.is_file():
            data = _checked(src, role, forbidden, placeholders=False)
            context_copies[role] = data
            inputs.append(_input_record(role, src, data, f"inputs/context/{role}.md"))
        else:
            inputs.append({"role": role, "source": str(src), "present": False})

    warnings: list[str] = []
    cfg_src = codex_home / "config.toml"
    if cfg_src.is_file():
        raw = cfg_src.read_bytes()
        redacted, n_redacted = redact_toml(raw.decode("utf-8", errors="replace"))
        if scan_bytes(redacted.encode("utf-8")):
            raise ToolError("config snapshot still matches a credential pattern after redaction; fix config.toml")
        tools = config_summary(redacted)
        if a.use_user_config and tools.get("parse_error"):
            raise ToolError(f"config.toml does not parse, so the tools it enables cannot be listed: {tools['parse_error']}")
        if not a.use_user_config and (tools.get("notify_hook_configured") or tools.get("plugins_enabled")
                                      or tools.get("mcp_servers")):
            warnings.append("config.toml enables hooks, plugins or MCP servers; they are ignored because "
                            "--use-user-config was not given")
        config = {"source": str(cfg_src), "present": True, "bytes": len(raw), "sha256": sha256_bytes(raw),
                  "snapshot": "harness/config.redacted.toml", "redactions": n_redacted,
                  "tools_listed_in_config": tools}
        config_snapshot = redacted.encode("utf-8")
    else:
        config = {"source": str(cfg_src), "present": False}
        tools = {}
        config_snapshot = None

    data_rows = load_data_manifest(a.data_manifest.resolve(), forbidden) if a.data_manifest else []
    for row in data_rows:
        if Path(row["path"]).is_relative_to(ws):
            warnings.append(f"data file is inside the workspace and can be edited by the agent: {row['path']}")
    if not data_rows:
        warnings.append("no data manifest given; the lock records no data hashes")

    harness = []
    for name in HARNESS_FILES:
        src = HERE / name
        if not src.is_file():
            raise ToolError(f"harness file missing: {src}")
        harness.append({"name": name, "bytes": src.stat().st_size, "sha256": sha256_file(src),
                        "run_copy": f"harness/{name}"})

    # All checks passed. Only now create the run directory.
    out.mkdir(parents=True, exist_ok=True)
    (out / "inputs" / "context").mkdir(parents=True)
    (out / "harness").mkdir()
    write_new(out / "inputs" / "prompt.md", prompt)
    write_new(out / "inputs" / "AGENTS.md", brief)
    for role, data in context_copies.items():
        write_new(out / "inputs" / "context" / f"{role}.md", data)
    for name in HARNESS_FILES:
        shutil.copyfile(HERE / name, out / "harness" / name)
    if config_snapshot is not None:
        write_new(out / "harness" / "config.redacted.toml", config_snapshot)
    write_new(out / "harness" / "codex_exec_help.txt", help_text.encode("utf-8"))
    write_new(out / "harness" / "codex_version.txt", (version + "\n").encode("utf-8"))

    last_message = out / "last_message.txt"
    exec_args = build_exec_args(ws, a.model, a.sandbox, a.approval, a.reasoning_effort,
                                not a.use_user_config, last_message)
    budget_s = int(round(a.hours * 3600))
    lock = {
        "schema": SCHEMA,
        "run_id": new_run_id(),
        "locked_at_utc": utc_now(),
        "framework": {
            "name": "OpenAI Codex CLI",
            "version": version,
            "bin": codex_path,
            "bin_sha256": sha256_file(Path(codex_path).resolve()),
            "exec_help_sha256": sha256_bytes(help_text.encode("utf-8")),
        },
        "model": a.model,
        "reasoning_effort": a.reasoning_effort,
        "tools_and_permissions": {
            "sandbox": a.sandbox,
            "approval_policy": a.approval,
            "user_config": "used" if a.use_user_config else "ignored",
            "tools_listed_in_config": tools,
            "enforcement": "Codex sandbox only; this tool adds no network or file policy of its own",
        },
        "budget": {"wall_clock_hours": a.hours, "wall_clock_seconds": budget_s},
        "launch": {
            "argv": [codex_path] + exec_args,
            "cwd": str(ws),
            "stdin": "inputs/prompt.md",
            "env": {"CODEX_HOME": str(codex_home),
                    "OPENAI_API_KEY": "set" if os.environ.get("OPENAI_API_KEY") else "unset"},
        },
        "workspace": str(ws),
        "codex_home": str(codex_home),
        "predictions_dir": pred_rel,
        "inputs": inputs,
        "config": config,
        "data": data_rows,
        "harness": harness,
        "warnings": warnings,
    }
    lock_bytes = (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8")
    write_new(out / "lock.json", lock_bytes)
    write_new(out / "lock.sha256", f"{sha256_bytes(lock_bytes)}  lock.json\n".encode("utf-8"))
    write_new(out / "command.txt", (" ".join(shlex.quote(x) for x in lock["launch"]["argv"]) + "\n").encode("utf-8"))

    print(f"LOCK WRITTEN: {out}")
    print(f"run_id={lock['run_id']} model={a.model} codex={version} sandbox={a.sandbox} "
          f"approval={a.approval} budget={budget_s}s data_files={len(data_rows)}")
    for w in warnings:
        print(f"warning: {w}")
    print("From here, run codex_launch.py on this directory. Do not read intermediate results before the run ends.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lock a Codex CLI run: prompt, brief, config, model, sandbox, budget, data.")
    ap.add_argument("--out", required=True, type=Path, help="new run directory (must not exist or be empty)")
    ap.add_argument("--prompt", required=True, type=Path, help="initial task prompt, read by Codex from stdin")
    ap.add_argument("--workspace", required=True, type=Path, help="directory the agent works in; must hold AGENTS.md")
    ap.add_argument("--model", required=True, help="exact model string, e.g. gpt-6-luna")
    ap.add_argument("--hours", required=True, type=float, help="wall-clock budget for the run")
    ap.add_argument("--sandbox", default="workspace-write", choices=SANDBOX_MODES)
    ap.add_argument("--approval", default="never", choices=APPROVAL_POLICIES)
    ap.add_argument("--reasoning-effort", default=None, choices=REASONING_EFFORTS)
    ap.add_argument("--data-manifest", type=Path, default=None)
    ap.add_argument("--predictions-dir", default="out/predictions",
                    help="relative to the workspace; must be empty at lock time")
    ap.add_argument("--codex-home", type=Path, default=None, help="default: $CODEX_HOME or ~/.codex")
    ap.add_argument("--codex-bin", default="codex")
    ap.add_argument("--use-user-config", action="store_true",
                    help="let Codex read config.toml (its hooks, plugins and MCP servers then run in the agent's session)")
    a = ap.parse_args(argv)
    try:
        return _lock(a)
    except ToolError as exc:
        print(f"codex_lock: refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
