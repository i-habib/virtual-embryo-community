"""Tests for prelock_audit. Every workspace and home is a synthetic temp directory."""

import hashlib
import json
import shutil
import subprocess

import pytest

import prelock_audit as pa


def write(root, files):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")


def audit(ws, cli, home, environ=None, **kwargs):
    kwargs.setdefault("use_git", False)
    return pa.run_audit(ws, cli, home=str(home), environ=environ or {}, **kwargs)


def by_verdict(findings, verdict):
    return [f for f in findings if f["verdict"] == verdict]


def entry_paths(record):
    return {e["path"]: e for e in record["context_files"]}


def project_key(ws):
    return str(ws.resolve()).replace("/", "-")


@pytest.fixture
def dirs(tmp_path):
    base = tmp_path.resolve()
    ws = base / "ws"
    home = base / "home"
    ws.mkdir()
    home.mkdir()
    return ws, home


# ---------------------------------------------------------------- inventory

def test_claude_loads_ancestors_and_user_file_with_hashes(dirs):
    ws, home = dirs
    parent_text = "Parent instructions.\n"
    ws_text = "Project instructions.\n"
    user_text = "User instructions.\n"
    write(ws.parent, {"CLAUDE.md": parent_text})
    write(ws, {"CLAUDE.md": ws_text})
    write(home, {".claude/CLAUDE.md": user_text})
    record, _ = audit(ws, "claude", home)
    entries = entry_paths(record)
    expected = {
        str(ws.parent / "CLAUDE.md"): parent_text,
        str(ws / "CLAUDE.md"): ws_text,
        str(home / ".claude" / "CLAUDE.md"): user_text,
    }
    for path, text in expected.items():
        assert path in entries, path
        assert entries[path]["loaded"] == "auto"
        assert entries[path]["sha256"] == hashlib.sha256(text.encode()).hexdigest()
        assert entries[path]["bytes"] == len(text.encode())


def test_claude_reads_agents_md_only_without_claude_md(dirs):
    ws, home = dirs
    write(ws, {"AGENTS.md": "Agents file.\n"})
    record, _ = audit(ws, "claude", home)
    assert entry_paths(record)[str(ws / "AGENTS.md")]["loaded"] == "auto"

    write(ws, {"CLAUDE.md": "Claude file.\n"})
    record, _ = audit(ws, "claude", home)
    assert entry_paths(record)[str(ws / "AGENTS.md")]["loaded"] == "not loaded"


def test_claude_memory_dir_matched_by_project_key(dirs):
    ws, home = dirs
    memory = home / ".claude" / "projects" / project_key(ws) / "memory"
    write(memory, {"MEMORY.md": "Index line.\n"})
    record, _ = audit(ws, "claude", home)
    assert record["auto_memory"]["enabled"] is True
    assert record["auto_memory"]["directory"] == str(memory)
    assert entry_paths(record)[str(memory / "MEMORY.md")]["loaded"] == "auto"


def test_auto_memory_disabled_by_env_is_info_and_not_loaded(dirs):
    ws, home = dirs
    memory = home / ".claude" / "projects" / project_key(ws) / "memory"
    write(memory, {"MEMORY.md": "Index line.\n"})
    record, findings = audit(ws, "claude", home, environ={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})
    assert record["auto_memory"]["enabled"] is False
    assert entry_paths(record)[str(memory / "MEMORY.md")]["loaded"] == "not loaded"
    assert any(f["category"] == "auto memory disabled" for f in by_verdict(findings, "INFO"))


def test_codex_override_wins_and_project_chain_root_first(dirs):
    ws, home = dirs
    root = ws
    write(home, {".codex/AGENTS.override.md": "Override.\n", ".codex/AGENTS.md": "Plain.\n"})
    write(root, {".git/config": "", "AGENTS.md": "Root file.\n", "sub/AGENTS.md": "Sub file.\n",
                 "sub/deeper/AGENTS.md": "Below cwd, not loaded.\n"})
    cwd = root / "sub"
    record, _ = audit(cwd, "codex", home)
    paths = [e["path"] for e in record["context_files"]]
    assert str(home / ".codex" / "AGENTS.override.md") in paths
    assert str(home / ".codex" / "AGENTS.md") not in paths
    root_idx = paths.index(str(root / "AGENTS.md"))
    sub_idx = paths.index(str(cwd / "AGENTS.md"))
    assert root_idx < sub_idx
    assert str(cwd / "deeper" / "AGENTS.md") not in paths


def test_codex_empty_override_falls_through(dirs):
    ws, home = dirs
    write(home, {".codex/AGENTS.override.md": "   \n", ".codex/AGENTS.md": "Plain.\n"})
    record, _ = audit(ws, "codex", home)
    paths = [e["path"] for e in record["context_files"]]
    assert str(home / ".codex" / "AGENTS.md") in paths
    assert str(home / ".codex" / "AGENTS.override.md") not in paths


def test_opencode_agents_beats_claude_fallback(dirs):
    ws, home = dirs
    write(ws, {"AGENTS.md": "Agents.\n", "CLAUDE.md": "Claude.\n"})
    record, _ = audit(ws, "opencode", home)
    paths = [e["path"] for e in record["context_files"]]
    assert str(ws / "AGENTS.md") in paths
    assert str(ws / "CLAUDE.md") not in paths


def test_opencode_claude_fallbacks_and_their_disable_flags(dirs):
    ws, home = dirs
    write(ws, {"CLAUDE.md": "Project claude.\n"})
    write(home, {".claude/CLAUDE.md": "User claude.\n"})
    record, _ = audit(ws, "opencode", home)
    paths = [e["path"] for e in record["context_files"]]
    assert str(ws / "CLAUDE.md") in paths
    assert str(home / ".claude" / "CLAUDE.md") in paths

    record, _ = audit(ws, "opencode", home, environ={"OPENCODE_DISABLE_CLAUDE_CODE": "1"})
    paths = [e["path"] for e in record["context_files"]]
    assert str(ws / "CLAUDE.md") not in paths
    assert str(home / ".claude" / "CLAUDE.md") not in paths


def test_imports_are_followed_and_recorded(dirs):
    ws, home = dirs
    write(ws, {"CLAUDE.md": "Start.\n@notes/plan.md\n", "notes/plan.md": "Plan text.\n"})
    record, _ = audit(ws, "claude", home)
    entry = entry_paths(record)[str(ws / "notes" / "plan.md")]
    assert entry["loaded"] == "auto"
    assert entry["imported_from"] == str(ws / "CLAUDE.md")


def test_generic_union_marks_everything_assumed(dirs):
    ws, home = dirs
    write(ws, {"GEMINI.md": "Gemini.\n", "AGENTS.md": "Agents.\n"})
    write(home, {".gemini/GEMINI.md": "Home gemini.\n"})
    record, _ = audit(ws, "generic", home)
    entries = entry_paths(record)
    assert entries[str(ws / "GEMINI.md")]["loaded"] == "assumed"
    assert entries[str(home / ".gemini" / "GEMINI.md")]["loaded"] == "assumed"
    assert entries[str(ws / "AGENTS.md")]["loaded"] == "assumed"


# ----------------------------------------------------------------- verdicts

def test_score_line_in_claude_md_is_block(dirs):
    ws, home = dirs
    write(ws, {"CLAUDE.md": "Current leaderboard best: 74.9 on the board.\n"})
    record, findings = audit(ws, "claude", home)
    blocks = by_verdict(findings, "BLOCK")
    assert blocks and blocks[0]["category"] == "score-like number"
    assert blocks[0]["line"] == 1
    assert "74.9" in blocks[0]["excerpt"]
    assert record["exit_code"] == 1


def test_score_in_workspace_notes_is_review_not_block(dirs):
    ws, home = dirs
    write(ws, {"notes/progress.md": "Scores on the board: 61.20 after the last change.\n"})
    record, findings = audit(ws, "claude", home)
    assert not by_verdict(findings, "BLOCK")
    reviews = by_verdict(findings, "REVIEW")
    assert any(f["category"] == "score-like number" and f["path"].endswith("progress.md") for f in reviews)
    assert record["exit_code"] == 0


def test_claude_subdirectory_claude_md_is_on_demand_context(dirs):
    ws, home = dirs
    write(ws, {"sub/CLAUDE.md": "Board score 70.12 noted here.\n"})
    _, findings = audit(ws, "claude", home)
    assert any(f["verdict"] == "BLOCK" and f["path"].endswith("sub/CLAUDE.md") for f in findings)


def test_version_strings_and_stage_tokens_are_not_numbers(dirs):
    ws, home = dirs
    write(ws, {"pkg/__init__.py": "__version__ = '0.4.1'\n", "notes/stage.md": "Heart stage E8.5 is validation only.\n"})
    _, findings = audit(ws, "claude", home)
    assert not any(f["category"] == "score-like number" for f in findings)
    assert pa.DECIMAL_RE.search(pa.STAGE_RE.sub(" ", "E8.5")) is None


def test_held_out_genotype_with_number_in_context_is_block(dirs):
    ws, home = dirs
    write(ws, {"CLAUDE.md": "Gata4 knockout at E8.75 gave 0.612 in the check.\n"})
    _, findings = audit(ws, "claude", home)
    assert any(f["verdict"] == "BLOCK" and f["category"] == "held-out marker with numbers" for f in findings)


def test_held_out_stage_mention_without_numbers_is_review(dirs):
    ws, home = dirs
    memory = home / ".claude" / "projects" / project_key(ws) / "memory"
    write(memory, {"notes.md": "Heart interp E8.5 is validation only.\n"})
    _, findings = audit(ws, "claude", home)
    assert not by_verdict(findings, "BLOCK")
    assert any(f["category"] == "held-out marker named" and f["verdict"] == "REVIEW" for f in findings)


def test_held_out_filename_in_memory_is_block_and_in_workspace_is_review(dirs):
    ws, home = dirs
    memory = home / ".claude" / "projects" / project_key(ws) / "memory"
    write(memory, {"E12.5_truth.h5ad": b"\x89HDF\x00\x00"})
    write(ws, {"data/E8.5_truth.csv": "a,b\n1,2\n"})
    _, findings = audit(ws, "claude", home)
    blocks = by_verdict(findings, "BLOCK")
    reviews = by_verdict(findings, "REVIEW")
    assert any(f["category"] == "held-out marker in file name" and "E12.5" in f["path"] for f in blocks)
    assert any(f["category"] == "held-out marker in file name" and "E8.5" in f["path"] for f in reviews)


def test_answer_and_score_file_names_are_review(dirs):
    ws, home = dirs
    write(ws, {"val_answers.csv": "x\n", "cache/scores.csv": "x\n", "scorer.py": "x = 1\n"})
    _, findings = audit(ws, "claude", home)
    reviews = {f["path"] for f in by_verdict(findings, "REVIEW")}
    assert str(ws / "val_answers.csv") in reviews
    assert str(ws / "cache" / "scores.csv") in reviews
    assert str(ws / "scorer.py") not in reviews


def test_secret_values_are_never_printed_or_stored(dirs, tmp_path, capsys):
    ws, home = dirs
    secret = "sk-" + "A" * 30
    write(ws, {".env": f"OPENAI_API_KEY={secret}\n", "config.py": "token = 'x'\n"})
    out = tmp_path / "out"
    code = pa.main(["--workspace", str(ws), "--cli", "claude", "--out", str(out),
                    "--home", str(home), "--no-git"])
    assert code == 0
    printed = capsys.readouterr().out
    lock = (out / "prelock_lock.json").read_text(encoding="utf-8")
    report = (out / "prelock_report.md").read_text(encoding="utf-8")
    for text in (printed, lock, report):
        assert secret not in text
        assert "A" * 30 not in text
    assert "OPENAI_API_KEY" in report
    assert any(f["category"] == "secret-like value" and f["verdict"] == "REVIEW"
               for f in json.loads(lock)["findings"])


def test_secret_line_withholds_score_on_same_line(dirs, tmp_path):
    ws, home = dirs
    write(ws, {"CLAUDE.md": "Board 74.9, token = \"abcdefghijk1234\"\n"})
    record, findings = audit(ws, "claude", home)
    text = json.dumps(record)
    assert "abcdefghijk1234" not in text
    assert not any(f["category"] == "score-like number" for f in findings)
    assert any(f["category"] == "secret-like value" for f in findings)


def test_redact_excerpts_removes_text(dirs):
    ws, home = dirs
    write(ws, {"CLAUDE.md": "Best leaderboard score 74.9 so far.\n"})
    record, findings = audit(ws, "claude", home, redact=True)
    blocks = by_verdict(findings, "BLOCK")
    assert blocks and blocks[0]["excerpt"] == pa.REDACTED
    assert "74.9" not in json.dumps(record)


def test_other_project_memory_is_names_only(dirs):
    ws, home = dirs
    write(home, {".claude/projects/-other-project/memory/MEMORY.md": "leaderboard 99.99 once\n"})
    record, findings = audit(ws, "claude", home)
    assert "99.99" not in json.dumps(record)
    info = [f for f in by_verdict(findings, "INFO") if f["category"] == "other project directories under the CLI home"]
    assert info and "1 other project directory" in info[0]["detail"]
    assert record["auto_memory"]["enabled"] is True


def test_binary_files_are_not_content_scanned(dirs):
    ws, home = dirs
    write(ws, {"blob.bin": b"\x00\x01leaderboard 1.23\n"})
    record, findings = audit(ws, "claude", home)
    assert not any(f["category"] == "score-like number" for f in findings)
    assert record["scan"]["content_skipped"] >= 1
    assert any(f["category"] == "content not scanned" for f in by_verdict(findings, "INFO"))


def test_extra_scan_shell_history_is_review(dirs):
    ws, home = dirs
    write(home, {".zsh_history": "echo leaderboard 80.10\n"})
    record, findings = audit(ws, "claude", home, extra_scan=[home / ".zsh_history"])
    assert any(f["category"] == "score-like number" and f["verdict"] == "REVIEW" for f in findings)
    assert record["exit_code"] == 0


def test_shell_history_without_extra_scan_is_info_only(dirs):
    ws, home = dirs
    write(home, {".zsh_history": "echo leaderboard 80.10\n"})
    _, findings = audit(ws, "claude", home)
    assert not any(f["category"] == "score-like number" for f in findings)
    assert any(f["category"] == "shell history present, not scanned" for f in by_verdict(findings, "INFO"))


def test_codex_history_scanned_for_codex_only(dirs):
    ws, home = dirs
    write(home, {".codex/history.jsonl": '{"text": "leaderboard 80.10"}\n'})
    _, claude_findings = audit(ws, "claude", home)
    _, codex_findings = audit(ws, "codex", home)
    assert not any(f["category"] == "score-like number" for f in claude_findings)
    assert any(f["category"] == "score-like number" and f["verdict"] == "REVIEW" for f in codex_findings)


def test_output_directory_inside_workspace_is_excluded(dirs, tmp_path, capsys):
    ws, home = dirs
    out = ws / "out"
    write(out, {"prelock_report.md": "leaderboard 74.9 from an earlier run\n"})
    code = pa.main(["--workspace", str(ws), "--cli", "claude", "--out", str(out),
                    "--home", str(home), "--no-git"])
    assert code == 0
    assert "warning" in capsys.readouterr().err
    lock = json.loads((out / "prelock_lock.json").read_text(encoding="utf-8"))
    assert not any(str(out) in f["path"] for f in lock["findings"])


def test_git_history_names_are_review(dirs, tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    ws, home = dirs
    git = ["git", "-C", str(ws), "-c", "user.email=t@example.com", "-c", "user.name=t"]
    subprocess.run(["git", "-C", str(ws), "init", "-q"], check=True)
    write(ws, {"leaderboard.csv": "x\n", "README.md": "ok\n"})
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "add"], check=True)
    subprocess.run(git + ["rm", "-q", "leaderboard.csv"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "remove"], check=True)
    record, findings = audit(ws, "claude", home, use_git=True)
    assert record["scan"]["git_history"] == "read"
    assert any(f["verdict"] == "REVIEW" and f["path"].startswith("git:") and "leaderboard" in f["path"]
               for f in findings)


def test_clean_workspace_exits_zero_with_no_block(dirs):
    ws, home = dirs
    write(ws, {"CLAUDE.md": "Use pytest for tests.\n", "README.md": "Code notes.\n"})
    record, findings = audit(ws, "claude", home)
    assert record["summary"]["BLOCK"] == 0
    assert record["exit_code"] == 0


# ------------------------------------------------------------ lock and CLI

def test_lock_record_schema_and_hashes(dirs, tmp_path):
    ws, home = dirs
    write(ws, {"CLAUDE.md": "Use pytest.\n"})
    out = tmp_path / "evidence"
    code = pa.main(["--workspace", str(ws), "--cli", "claude", "--out", str(out),
                    "--home", str(home), "--no-git"])
    assert code == 0
    lock = json.loads((out / "prelock_lock.json").read_text(encoding="utf-8"))
    assert lock["schema"] == pa.SCHEMA
    assert lock["cli"] == "claude"
    assert lock["cli_rule_source"] == pa.RULE_SOURCES["claude"]
    assert lock["timestamp_utc"].endswith("+00:00")
    assert set(lock["env_flags_set"]) == set(pa.ENV_FLAGS)
    assert all(isinstance(v, bool) for v in lock["env_flags_set"].values())
    entry = next(e for e in lock["context_files"] if e["path"].endswith("CLAUDE.md"))
    assert len(entry["sha256"]) == 64
    assert entry["sha256"] == hashlib.sha256((ws / "CLAUDE.md").read_bytes()).hexdigest()
    assert lock["overall"] in {"BLOCK", "REVIEW", "INFO"}
    report = (out / "prelock_report.md").read_text(encoding="utf-8")
    assert "## Findings" in report and "### BLOCK" in report and "### REVIEW" in report and "### INFO" in report


def test_main_returns_one_on_block_and_writes_outputs(dirs, tmp_path, capsys):
    ws, home = dirs
    write(ws, {"AGENTS.md": "Leaderboard best 74.9.\n"})
    out = tmp_path / "evidence"
    code = pa.main(["--workspace", str(ws), "--cli", "generic", "--out", str(out),
                    "--home", str(home), "--no-git"])
    assert code == 1
    assert (out / "prelock_lock.json").is_file()
    assert (out / "prelock_report.md").is_file()
    printed = capsys.readouterr().out
    assert "overall=BLOCK" in printed and "exit=1" in printed


def test_main_usage_error_for_missing_workspace(tmp_path, capsys):
    code = pa.main(["--workspace", str(tmp_path / "missing"), "--cli", "codex", "--out", str(tmp_path / "o")])
    assert code == 2


def test_unknown_cli_rejected_by_argparse(tmp_path):
    with pytest.raises(SystemExit):
        pa.main(["--workspace", str(tmp_path), "--cli", "gemini", "--out", str(tmp_path / "o")])
