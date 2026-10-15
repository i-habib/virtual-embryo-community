#!/usr/bin/env python3
"""Build the evidence bundle for a finished, locked Codex CLI run.

Usage:
  codex_package.py RUNDIR --out BUNDLEDIR [--team-uploaded-mb MB] [--allow-empty]

Refuses (and writes nothing) when: the lock or any locked input changed; the run did not finish;
the prediction directory differs from the snapshot taken when the run ended; there are no
predictions (unless --allow-empty); a credential-shaped string is in any packaged file; a file or
zip is over the 200 MB evidence cap; a prediction file is over the 1200 MB cap.

BUNDLEDIR receives trajectory.zip, prompts.zip, harness.zip, evidence_manifest.json and README.md.
Prediction files are not copied; the manifest records their sizes and SHA-256 so the upload uses
the unchanged files from the workspace.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path

import codex_common as cc
from codex_common import (
    HARNESS_FILES, SCHEMA, ToolError, check_locked_state, credential_hashes, credential_reason,
    inspect_file, load_json, load_lock, scan_bytes, sha256_bytes, sha256_file, tree_listing, utc_now,
)


def summarise_stream(path: Path, locked_model: str) -> tuple[dict, list[str]]:
    """Counts from the `codex exec --json` stream. Event names are read as documented, not verified live."""
    types: Counter = Counter()
    item_types: Counter = Counter()
    usage: Counter = Counter()
    models: set[str] = set()
    lines = bad = turns_completed = turns_failed = errors = 0
    thread_id = None
    last_type = None

    def collect_models(obj, depth=0):
        if depth > 6 or len(models) > 10:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "model" and isinstance(v, str):
                    models.add(v)
                else:
                    collect_models(v, depth + 1)
        elif isinstance(obj, list):
            for v in obj[:200]:
                collect_models(v, depth + 1)

    with open(path, "rb") as fh:
        for raw in fh:
            lines += 1
            try:
                ev = json.loads(raw)
            except ValueError:
                bad += 1
                continue
            if not isinstance(ev, dict):
                bad += 1
                continue
            t = str(ev.get("type") or (ev.get("msg") or {}).get("type") or "unknown")
            types[t] += 1
            last_type = t
            if thread_id is None:
                thread_id = cc.thread_id_from_event(ev)
            if t == "item.completed" and isinstance(ev.get("item"), dict):
                item_types[str(ev["item"].get("type", "unknown"))] += 1
            if t == "turn.completed":
                turns_completed += 1
                u = ev.get("usage") if isinstance(ev.get("usage"), dict) else {}
                for k, v in u.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        usage[k] += v
            if t == "turn.failed":
                turns_failed += 1
            if "error" in t.lower():
                errors += 1
            collect_models(ev)

    json_events = lines - bad
    warnings = []
    if json_events == 0:
        warnings.append("the stream holds no JSON events; the trajectory is still a byte copy")
    if bad:
        warnings.append(f"{bad} stream line(s) were not JSON; they are kept byte for byte")
    if turns_completed == 0:
        warnings.append("no turn.completed event in the stream")
    if models and locked_model not in models:
        warnings.append(f"the stream names model(s) {sorted(models)}, not the locked string {locked_model!r}")
    summary = {
        "parser_note": "event names follow the Codex non-interactive docs as read by the kit; check against your codex version",
        "lines": lines, "json_events": json_events, "non_json_lines": bad,
        "thread_id": thread_id, "event_types": dict(types), "last_event_type": last_type,
        "turns_completed": turns_completed, "turns_failed": turns_failed, "error_events": errors,
        "completed_item_types": dict(item_types), "usage_summed_over_turns": dict(usage),
        "models_named_in_stream": sorted(models),
    }
    return summary, warnings


def _members_for(run: Path, lock: dict, state: dict) -> dict[str, list[tuple[str, Path]]]:
    groups: dict[str, list[tuple[str, Path]]] = {"trajectory": [], "prompts": [], "harness": []}
    groups["trajectory"].append(("trajectory/stream.jsonl", run / "trajectory.jsonl"))
    for name, arc in (("stderr.log", "trajectory/stderr.log"), ("last_message.txt", "trajectory/last_message.txt")):
        if (run / name).is_file():
            groups["trajectory"].append((arc, run / name))
    for row in state.get("rollouts", []):
        groups["trajectory"].append((f"trajectory/rollout/{row['name']}", run / row["copy"]))

    arc_for = {"prompt": "prompts/prompt.md", "workspace_agents": "prompts/AGENTS.md"}
    for inp in lock["inputs"]:
        if inp["present"]:
            arc = arc_for.get(inp["role"], f"prompts/context/{inp['role']}.md")
            groups["prompts"].append((arc, run / inp["run_copy"]))

    for name in HARNESS_FILES:
        groups["harness"].append((f"harness/{name}", run / "harness" / name))
    for name in ("lock.json", "lock.sha256", "launch_state.json", "predictions_at_end.json"):
        groups["harness"].append((f"harness/{name}", run / name))
    for name in ("config.redacted.toml", "codex_exec_help.txt", "codex_version.txt"):
        if (run / "harness" / name).is_file():
            groups["harness"].append((f"harness/{name}", run / "harness" / name))
    return groups


def _package(run: Path, out: Path, uploaded_mb: float, allow_empty: bool) -> int:
    if out.exists() and any(out.iterdir()):
        raise ToolError(f"{out} exists and is not empty")
    lock = load_lock(run)
    state_path = run / "launch_state.json"
    if not state_path.is_file():
        raise ToolError("the run was never launched (no launch_state.json)")
    state = load_json(state_path)
    if state.get("status") != "finished":
        raise ToolError(f"the run did not finish (status {state.get('status')!r}); make a new lock for a new run")
    problems = check_locked_state(run, lock)
    if problems:
        raise ToolError("locked inputs changed; the bundle would not match the lock:\n  " + "\n  ".join(problems))

    pred_dir = Path(lock["workspace"]) / lock["predictions_dir"]
    at_end = load_json(run / "predictions_at_end.json")["files"]
    now = tree_listing(pred_dir)
    if now != at_end:
        before = {r["path"]: r["sha256"] for r in at_end}
        after = {r["path"]: r["sha256"] for r in now}
        diffs = [f"added after run end: {p}" for p in sorted(set(after) - set(before))]
        diffs += [f"removed after run end: {p}" for p in sorted(set(before) - set(after))]
        diffs += [f"changed after run end: {p}" for p in sorted(set(before) & set(after)) if before[p] != after[p]]
        raise ToolError("prediction files changed after the run ended:\n  " + "\n  ".join(diffs or ["(order or metadata)"]))
    if not now and not allow_empty:
        raise ToolError("the run wrote no prediction files (use --allow-empty to package the trajectory anyway)")
    for row in now:
        if row["bytes"] > cc.MAX_PREDICTION_FILE_BYTES:
            raise ToolError(f"prediction file over the 1200 MB cap: {row['path']}")

    forbidden = credential_hashes(Path(lock["codex_home"]))
    warnings: list[str] = []
    if state.get("exit_code") not in (0, None):
        warnings.append(f"codex exited with code {state['exit_code']}")
    if state.get("timed_out"):
        warnings.append("the run reached its wall-clock budget and was stopped")
    if not state.get("rollouts"):
        warnings.append("no Codex session file was packaged")
    warnings += state.get("warnings", [])
    warnings += [f"lock warning: {w}" for w in lock.get("warnings", [])]

    stream_summary, stream_warnings = summarise_stream(run / "trajectory.jsonl", lock["model"])
    warnings += stream_warnings
    if (run / "trajectory.jsonl").stat().st_size < 100_000_000:
        stream_bytes = (run / "trajectory.jsonl").read_bytes()
        for row in now:
            name = Path(row["path"]).name
            if name.encode() not in stream_bytes:
                warnings.append(f"prediction {row['path']} is not named in the stream (weak provenance)")
    else:
        warnings.append("stream is over 100 MB; the check that predictions are named in it was skipped")
    summary_bytes = (json.dumps(stream_summary, indent=2, sort_keys=True) + "\n").encode("utf-8")

    groups = _members_for(run, lock, state)
    groups["trajectory"].append(("trajectory/summary.json", None))  # generated bytes, added below
    archives: dict[str, list[dict]] = {}
    plan: dict[str, list[tuple[str, object]]] = {}
    for kind, members in groups.items():
        rows, entries = [], []
        for arc, src in members:
            if src is None:
                data = summary_bytes
                sha, hits = sha256_bytes(data), scan_bytes(data)
                size = len(data)
                entries.append((arc, data))
            else:
                if not src.is_file():
                    raise ToolError(f"expected file missing from the run directory: {src}")
                reason = credential_reason(src, forbidden)
                if reason:
                    raise ToolError(f"refused to package {src}: {reason}")
                size = src.stat().st_size
                sha, hits = inspect_file(src)
                entries.append((arc, src))
            if hits:
                raise ToolError(f"{arc} contains credential-shaped text ({', '.join(hits)}); nothing was written")
            if size > cc.MAX_EVIDENCE_FILE_BYTES:
                raise ToolError(f"{arc} is {size} bytes, over the 200 MB per-file cap; it cannot be truncated silently, "
                                "so file it in full and summarise it, or split it")
            rows.append({"name": arc, "bytes": size, "sha256": sha})
        archives[kind] = rows
        plan[kind] = entries

    out.mkdir(parents=True, exist_ok=True)
    try:
        zip_rows = []
        for kind in ("trajectory", "prompts", "harness"):
            zpath = out / f"{kind}.zip"
            with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for arc, src in plan[kind]:
                    if isinstance(src, bytes):
                        zf.writestr(arc, src)
                    else:
                        zf.write(src, arc)
            size = zpath.stat().st_size
            if size > cc.MAX_EVIDENCE_FILE_BYTES:
                raise ToolError(f"{zpath.name} is {size} bytes after compression, over the 200 MB cap")
            zip_rows.append({"name": zpath.name, "kind": kind, "bytes": size, "sha256": sha256_file(zpath),
                             "members": archives[kind]})

        team_total = sum(z["bytes"] for z in zip_rows)
        if uploaded_mb * 1_000_000 + team_total > cc.TEAM_EVIDENCE_CAP_BYTES:
            warnings.append(f"this bundle ({team_total / 1e6:.1f} MB) with {uploaded_mb:g} MB already uploaded "
                            "would exceed the 600 MB per-team cap")

        manifest = {
            "schema": SCHEMA,
            "kind": "codex-evidence-bundle",
            "packaged_utc": utc_now(),
            "run_id": lock["run_id"],
            "framework": {"name": lock["framework"]["name"], "version": lock["framework"]["version"]},
            "model": lock["model"],
            "reasoning_effort": lock["reasoning_effort"],
            "tools_and_permissions": lock["tools_and_permissions"],
            "budget_seconds": lock["budget"]["wall_clock_seconds"],
            "launch": {k: state.get(k) for k in ("started_utc", "ended_utc", "duration_seconds", "exit_code",
                                                 "returncode", "signal", "timed_out", "thread_id", "rollout_match")},
            "lock_sha256": sha256_file(run / "lock.json"),
            "checks": {
                "lock_and_locked_inputs_unchanged": True,
                "predictions_unchanged_since_run_end": True,
                "credential_scan": "no credential-pattern names matched in any packaged file",
                "per_file_cap_bytes": cc.MAX_EVIDENCE_FILE_BYTES,
            },
            "archives": zip_rows,
            "predictions": now,
            "stream_summary": stream_summary,
            "team_cap": {"this_bundle_bytes": team_total, "team_uploaded_mb": uploaded_mb,
                         "team_cap_bytes": cc.TEAM_EVIDENCE_CAP_BYTES},
            "warnings": warnings,
        }
        (out / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (out / "README.md").write_text(_readme(manifest, lock), encoding="utf-8")
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise

    print(f"BUNDLE WRITTEN: {out}")
    for z in zip_rows:
        print(f"  {z['name']}: {z['bytes']} bytes")
    print(f"  predictions listed (not copied): {len(now)}")
    for w in warnings:
        print(f"warning: {w}")
    return 0


def _readme(m: dict, lock: dict) -> str:
    tp = m["tools_and_permissions"]
    la = m["launch"]
    lines = [
        f"# Evidence bundle for run {m['run_id']}",
        "",
        "## Submission statement",
        "",
        f"- Framework: {m['framework']['name']}, `codex exec`, version `{m['framework']['version']}`.",
        f"- Model string as run (exact, from the lock): `{m['model']}`.",
        f"- Reasoning effort: {m['reasoning_effort'] or 'Codex default'}.",
        f"- Sandbox: `{tp['sandbox']}`. Approval policy: `{tp['approval_policy']}`. "
        f"User config: {tp['user_config']}.",
        "",
        "## Run",
        "",
        f"- Lock: `lock.json`, SHA-256 `{m['lock_sha256']}`.",
        f"- Started {la.get('started_utc')}, ended {la.get('ended_utc')}, "
        f"duration {la.get('duration_seconds')} s, budget {m['budget_seconds']} s.",
        f"- Exit code {la.get('exit_code')}; timed out: {la.get('timed_out')}.",
        f"- Session id: {la.get('thread_id') or 'not found'} (matched by {la.get('rollout_match') or 'n/a'}).",
        "",
        "## Files",
        "",
        "| archive | kind | bytes | SHA-256 |",
        "|---|---|---|---|",
    ]
    for z in m["archives"]:
        lines.append(f"| {z['name']} | {z['kind']} | {z['bytes']} | `{z['sha256']}` |")
    lines += [
        "",
        "Predictions (not copied here; upload the unchanged files from the workspace):",
        "",
    ]
    if m["predictions"]:
        for p in m["predictions"]:
            lines.append(f"- `{p['path']}`, {p['bytes']} bytes, SHA-256 `{p['sha256']}`")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Checks run at packaging",
        "",
        "- The lock and every locked input (prompt, AGENTS.md, context files, config.toml, data files,",
        "  tool scripts, codex binary) match their recorded SHA-256 values.",
        "- The prediction directory is identical to the snapshot taken when the run ended.",
        "- No packaged file matches a credential pattern (names of matched patterns are not reproduced).",
        f"- No file or zip is over {m['checks']['per_file_cap_bytes']} bytes.",
        "",
        "## Warnings",
        "",
    ]
    lines += [f"- {w}" for w in m["warnings"]] or ["- none"]
    lines += [
        "",
        "## What this bundle does not show",
        "",
        "- Codex's sandbox is the only enforcement layer. The lock records settings; it does not stop",
        "  the agent from reading anything the sandbox allows, including other run directories.",
        "- Hashes show what changed and what did not. They do not prove that no person intervened.",
        "- `config.redacted.toml` is a redacted copy. The lock stores a SHA-256 of the raw file, not the raw file.",
        "- Session files are copied byte for byte. This tool does not decompress them, and their",
        "  event names were not checked against this codex version.",
        "- This bundle does not certify compliance with the challenge rules. The organisers decide that.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Package the evidence for a finished, locked Codex run.")
    ap.add_argument("run", type=Path, help="run directory created by codex_lock.py")
    ap.add_argument("--out", required=True, type=Path, help="new directory for the bundle")
    ap.add_argument("--team-uploaded-mb", type=float, default=0.0,
                    help="evidence your team already uploaded, in MB, from your own records")
    ap.add_argument("--allow-empty", action="store_true", help="package even if no prediction files exist")
    a = ap.parse_args(argv)
    try:
        return _package(a.run.resolve(), a.out.resolve(), a.team_uploaded_mb, a.allow_empty)
    except ToolError as exc:
        print(f"codex_package: refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
