"""Tests for the Codex lock / launch / package tool.

No model is called. A fake `codex` executable is put first on PATH; it answers --version and
`exec --help`, reads the prompt from stdin, prints a few `--json` events, writes a session file
under $CODEX_HOME/sessions and writes a prediction file into the workspace.

Run from the codex-agent-run directory:
    python -m pytest -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))

import codex_common as cc  # noqa: E402
import codex_package  # noqa: E402

PY = sys.executable

# Fake secrets are assembled from pieces so this file never holds a credential-shaped literal.
FAKE_GH = "ghp" + "_" + "a" * 36
FAKE_SK = "s" + "k-" + "b" * 30
SECRET_VALUE = "supersecretvalue123"

HELP = "Run Codex non-interactively\n\nOptions:\n" + "\n".join(f"  {f}" for f in cc.REQUIRED_EXEC_FLAGS) + "\n  -c, --config <key=value>\n"

CONFIG = f'''model = "gpt-test"
approval_policy = "on-request"
notify = ["/bin/echo", "turn-ended"]

[mcp_servers.docs]
command = "docs-mcp"

[mcp_servers.docs.env]
DOCS_TOKEN = "{FAKE_GH}"

[plugins."chrome@x"]
enabled = true

[model_providers.custom]
api_key = "{SECRET_VALUE}"
base_url = "https://example.invalid/v1"
'''

FAKE_CODEX = r'''#!__PY__
import json, os, pathlib, sys, time, uuid
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 0.0.0-fake")
    sys.exit(0)
if args == ["exec", "--help"]:
    print(pathlib.Path(os.environ["FAKE_CODEX_HELP"]).read_text())
    sys.exit(0)
prompt = sys.stdin.read()
cwd = args[args.index("--cd") + 1]
model = args[args.index("--model") + 1]
home = pathlib.Path(os.environ["CODEX_HOME"])
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
log = os.environ.get("FAKE_CODEX_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"argv": args, "stdin": prompt, "cwd": os.getcwd(),
                             "codex_home": str(home)}) + "\n")
tid = "00000000-0000-4000-8000-" + os.urandom(6).hex()
sess = home / "sessions" / "2026" / "10" / "14"
sess.mkdir(parents=True, exist_ok=True)
with open(sess / f"rollout-2026-10-14T10-00-00-{tid}.jsonl", "w") as fh:
    fh.write(json.dumps({"type": "session_meta", "payload": {"id": tid}}) + "\n")
    fh.write(json.dumps({"type": "user_message", "text": prompt}) + "\n")
events = [
    {"type": "thread.started", "thread_id": tid},
    {"type": "turn.started"},
    {"type": "item.started", "item": {"type": "command_execution", "command": "ls"}},
    {"type": "item.completed", "item": {"type": "command_execution", "command": "ls", "exit_code": 0}},
    {"type": "item.completed", "item": {"type": "agent_message",
                                        "text": "wrote out/predictions/T3_gata4.h5ad"}},
]
if mode == "leak":
    events.append({"type": "item.completed", "item": {"type": "agent_message",
                   "text": '{"access_token": "abcdefgh12345678"}'}})
events.append({"type": "turn.completed", "model": model,
               "usage": {"input_tokens": 10, "output_tokens": 5}})
for ev in events:
    print(json.dumps(ev), flush=True)
if "--output-last-message" in args:
    pathlib.Path(args[args.index("--output-last-message") + 1]).write_text("done\n")
if mode == "sleep":
    time.sleep(60)
pred = pathlib.Path(cwd) / "out" / "predictions"
pred.mkdir(parents=True, exist_ok=True)
(pred / "T3_gata4.h5ad").write_bytes(b"fake prediction bytes")
sys.exit(1 if mode == "fail" else 0)
'''


@pytest.fixture
def world(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "codex"
    fake.write_text(FAKE_CODEX.replace("__PY__", PY))
    fake.chmod(0o755)
    help_file = tmp_path / "help.txt"
    help_file.write_text(HELP)
    home = tmp_path / "codex_home"
    home.mkdir()
    (home / "config.toml").write_text(CONFIG)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "AGENTS.md").write_text("# Brief\n\nPredict the held-out-free target. Write to out/predictions.\n")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Do the task described in AGENTS.md.\n")
    data = tmp_path / "data"
    data.mkdir()
    (data / "train.h5ad").write_bytes(b"x" * 100)
    manifest = tmp_path / "data_manifest.json"
    manifest.write_text(json.dumps({"files": ["data/train.h5ad"]}))
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    env["CODEX_HOME"] = str(home)
    env["FAKE_CODEX_HELP"] = str(help_file)
    env["FAKE_CODEX_LOG"] = str(tmp_path / "fake_log.jsonl")
    env.pop("OPENAI_API_KEY", None)
    monkeypatch.setenv("PATH", env["PATH"])
    return {"env": env, "home": home, "ws": ws, "prompt": prompt, "manifest": manifest,
            "tmp": tmp_path, "log": tmp_path / "fake_log.jsonl"}


def cli(script: str, args: list, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(TOOL / script), *map(str, args)], env=env, capture_output=True,
                          text=True, timeout=300)


def lock(w, run: Path, hours: str = "0.01", *extra) -> subprocess.CompletedProcess:
    return cli("codex_lock.py", ["--out", run, "--prompt", w["prompt"], "--workspace", w["ws"],
                                 "--model", "gpt-test", "--hours", hours,
                                 "--data-manifest", w["manifest"], *extra], w["env"])


def launch(w, run: Path, mode: str = "ok") -> subprocess.CompletedProcess:
    env = dict(w["env"])
    env["FAKE_CODEX_MODE"] = mode
    return cli("codex_launch.py", [run], env)


def package(w, run: Path, out: Path, *extra) -> subprocess.CompletedProcess:
    return cli("codex_package.py", [run, "--out", out, *extra], w["env"])


def read_state(run: Path) -> dict:
    return json.loads((run / "launch_state.json").read_text())


# ---------------------------------------------------------------- lock

def test_lock_writes_lock_and_refuses_overwrite(world):
    run = world["tmp"] / "run1"
    r = lock(world, run)
    assert r.returncode == 0, r.stderr
    lock_json = run / "lock.json"
    assert cc.sha256_file(lock_json) == (run / "lock.sha256").read_text().split()[0]
    data = json.loads(lock_json.read_bytes())
    argv = data["launch"]["argv"]
    for flag in ("--json", "--ignore-user-config", "--skip-git-repo-check"):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("--model") + 1] == "gpt-test"
    assert argv[-1] == "-"
    assert data["budget"]["wall_clock_seconds"] == 36
    assert data["framework"]["version"] == "codex-cli 0.0.0-fake"
    again = lock(world, run)
    assert again.returncode == 2
    assert "already exists" in again.stderr


def test_lock_refuses_full_access_sandbox(world):
    run = world["tmp"] / "run_full"
    r = lock(world, run, "0.01", "--sandbox", "danger-full-access")
    assert r.returncode != 0
    assert not run.exists()


def test_lock_refuses_placeholder_and_secret_in_prompt(world):
    world["prompt"].write_text("Use {{DATA_ROOT}} for data.\n")
    r = lock(world, world["tmp"] / "run_ph")
    assert r.returncode == 2 and "placeholder" in r.stderr
    world["prompt"].write_text("key " + "s" + "k-" + "c" * 30 + "\n")
    r = lock(world, world["tmp"] / "run_secret")
    assert r.returncode == 2 and "credential-shaped" in r.stderr


def test_lock_refuses_brief_with_operator_block(world):
    (world["ws"] / "AGENTS.md").write_text("<!-- BEGIN OPERATOR-ONLY -->\nnotes\n<!-- END -->\n# Brief\n")
    r = lock(world, world["tmp"] / "run_op")
    assert r.returncode == 2 and "OPERATOR-ONLY" in r.stderr


def test_lock_refuses_credential_named_data_file(world):
    (world["tmp"] / "data" / "auth.json").write_text("{}")
    world["manifest"].write_text(json.dumps({"files": ["data/auth.json"]}))
    r = lock(world, world["tmp"] / "run_cred")
    assert r.returncode == 2 and "credential" in r.stderr


def test_lock_refuses_leftover_predictions(world):
    pred = world["ws"] / "out" / "predictions"
    pred.mkdir(parents=True)
    (pred / "old.h5ad").write_bytes(b"old")
    r = lock(world, world["tmp"] / "run_left")
    assert r.returncode == 2 and "not empty" in r.stderr


def test_redaction_removes_secrets_and_lists_tools():
    text, n = cc.redact_toml(CONFIG)
    assert n == 2  # DOCS_TOKEN (env table) and api_key (secret-looking key)
    assert SECRET_VALUE not in text
    assert FAKE_GH not in text
    assert "<redacted>" in text
    summary = cc.config_summary(text)
    assert summary["parse_error"] is None
    assert summary["mcp_servers"] == ["docs"]
    assert summary["plugins_enabled"] == ["chrome@x"]
    assert summary["notify_hook_configured"] is True
    assert cc.scan_bytes(text.encode()) == []


def test_tool_sources_hold_no_credential_shaped_text():
    for name in cc.HARNESS_FILES:
        assert cc.scan_bytes((TOOL / name).read_bytes()) == [], name


# ---------------------------------------------------------------- launch

def test_launch_end_to_end(world):
    run = world["tmp"] / "run_ok"
    assert lock(world, run).returncode == 0
    r = launch(world, run)
    assert r.returncode == 0, r.stderr
    events = [json.loads(line) for line in (run / "trajectory.jsonl").read_text().splitlines()]
    assert events[0]["type"] == "thread.started"
    assert (run / "stderr.log").exists()
    state = read_state(run)
    assert state["status"] == "finished"
    assert state["exit_code"] == 0
    assert state["timed_out"] is False
    assert state["thread_id"] == events[0]["thread_id"]
    assert len(state["rollouts"]) == 1
    assert state["rollouts"][0]["matched_by"] == "session id"
    assert (run / state["rollouts"][0]["copy"]).is_file()
    assert state["inputs_changed_during_run"] == []
    preds = json.loads((run / "predictions_at_end.json").read_text())["files"]
    assert [p["path"] for p in preds] == ["T3_gata4.h5ad"]
    logged = json.loads(world["log"].read_text().splitlines()[0])
    assert logged["stdin"] == "Do the task described in AGENTS.md.\n"
    assert Path(logged["codex_home"]).resolve() == world["home"].resolve()
    assert "--json" in logged["argv"]


def test_launch_refuses_when_prompt_edited_after_lock(world):
    run = world["tmp"] / "run_edit"
    assert lock(world, run).returncode == 0
    world["prompt"].write_text("A different prompt.\n")
    r = launch(world, run)
    assert r.returncode == 2 and "source changed" in r.stderr
    assert not (run / "launch_state.json").exists()


def test_launch_refuses_tampered_lock(world):
    run = world["tmp"] / "run_tamper"
    assert lock(world, run).returncode == 0
    data = json.loads((run / "lock.json").read_text())
    data["model"] = "some-other-model"
    (run / "lock.json").write_text(json.dumps(data))
    r = launch(world, run)
    assert r.returncode == 2 and "does not match lock.sha256" in r.stderr


def test_launch_is_once_only(world):
    run = world["tmp"] / "run_once"
    assert lock(world, run).returncode == 0
    assert launch(world, run).returncode == 0
    r = launch(world, run)
    assert r.returncode == 2 and "already launched" in r.stderr


def test_budget_kills_the_run(world):
    run = world["tmp"] / "run_timeout"
    assert lock(world, run, "0.0008").returncode == 0
    r = launch(world, run, mode="sleep")
    assert r.returncode == 124
    state = read_state(run)
    assert state["timed_out"] is True
    assert state["status"] == "finished"
    assert state["duration_seconds"] < 30


def test_nonzero_exit_is_recorded(world):
    run = world["tmp"] / "run_fail"
    assert lock(world, run).returncode == 0
    r = launch(world, run, mode="fail")
    assert r.returncode == 1
    assert read_state(run)["exit_code"] == 1


# ---------------------------------------------------------------- package

def test_package_builds_bundle(world):
    run = world["tmp"] / "run_pkg"
    out = world["tmp"] / "bundle"
    assert lock(world, run).returncode == 0
    assert launch(world, run).returncode == 0
    r = package(world, run, out, "--team-uploaded-mb", "10")
    assert r.returncode == 0, r.stderr
    for name in ("trajectory.zip", "prompts.zip", "harness.zip", "evidence_manifest.json", "README.md"):
        assert (out / name).is_file(), name
    with zipfile.ZipFile(out / "trajectory.zip") as zf:
        names = zf.namelist()
        assert "trajectory/stream.jsonl" in names
        assert "trajectory/summary.json" in names
        assert any(n.startswith("trajectory/rollout/") for n in names)
    with zipfile.ZipFile(out / "prompts.zip") as zf:
        assert set(zf.namelist()) >= {"prompts/prompt.md", "prompts/AGENTS.md"}
    with zipfile.ZipFile(out / "harness.zip") as zf:
        assert set(zf.namelist()) >= {f"harness/{n}" for n in cc.HARNESS_FILES} | {"harness/lock.json"}
    manifest = json.loads((out / "evidence_manifest.json").read_text())
    assert manifest["framework"]["version"] == "codex-cli 0.0.0-fake"
    assert manifest["model"] == "gpt-test"
    assert manifest["predictions"][0]["path"] == "T3_gata4.h5ad"
    assert manifest["team_cap"]["this_bundle_bytes"] > 0
    readme = (out / "README.md").read_text()
    assert "gpt-test" in readme and "codex-cli 0.0.0-fake" in readme
    for z in manifest["archives"]:
        assert z["bytes"] <= cc.MAX_EVIDENCE_FILE_BYTES
    # No secret from config.toml reached the evidence.
    for name in ("trajectory.zip", "prompts.zip", "harness.zip"):
        with zipfile.ZipFile(out / name) as zf:
            for member in zf.namelist():
                assert SECRET_VALUE.encode() not in zf.read(member), (name, member)


def test_package_refuses_unlaunched_run(world):
    run = world["tmp"] / "run_nolaunch"
    assert lock(world, run).returncode == 0
    r = package(world, run, world["tmp"] / "b1")
    assert r.returncode == 2 and "never launched" in r.stderr
    assert not (world["tmp"] / "b1").exists()


def test_package_refuses_prediction_edited_after_run(world):
    run = world["tmp"] / "run_prededit"
    assert lock(world, run).returncode == 0
    assert launch(world, run).returncode == 0
    pred = world["ws"] / "out" / "predictions" / "T3_gata4.h5ad"
    pred.write_bytes(b"hand edited")
    r = package(world, run, world["tmp"] / "b2")
    assert r.returncode == 2 and "changed after run end" in r.stderr
    assert not (world["tmp"] / "b2").exists()


def test_package_refuses_prediction_added_after_run(world):
    run = world["tmp"] / "run_predadd"
    assert lock(world, run).returncode == 0
    assert launch(world, run).returncode == 0
    (world["ws"] / "out" / "predictions" / "extra.h5ad").write_bytes(b"added later")
    r = package(world, run, world["tmp"] / "b3")
    assert r.returncode == 2 and "added after run end" in r.stderr


def test_package_refuses_brief_changed_after_run(world):
    run = world["tmp"] / "run_briefedit"
    assert lock(world, run).returncode == 0
    assert launch(world, run).returncode == 0
    (world["ws"] / "AGENTS.md").write_text("# changed\n")
    r = package(world, run, world["tmp"] / "b4")
    assert r.returncode == 2 and "workspace_agents" in r.stderr


def test_package_refuses_credential_in_stream(world):
    run = world["tmp"] / "run_leak"
    assert lock(world, run).returncode == 0
    assert launch(world, run, mode="leak").returncode == 0
    r = package(world, run, world["tmp"] / "b5")
    assert r.returncode == 2 and "credential-shaped" in r.stderr
    assert not (world["tmp"] / "b5").exists()


def test_package_refuses_file_over_cap(world, monkeypatch, capsys):
    run = world["tmp"] / "run_cap"
    assert lock(world, run).returncode == 0
    assert launch(world, run).returncode == 0
    monkeypatch.setattr(cc, "MAX_EVIDENCE_FILE_BYTES", 50)
    rc = codex_package.main([str(run), "--out", str(world["tmp"] / "b6")])
    assert rc == 2
    assert "200 MB per-file cap" in capsys.readouterr().err


def test_summary_counts_and_unknown_lines(tmp_path):
    stream = tmp_path / "s.jsonl"
    stream.write_text(
        json.dumps({"type": "thread.started", "thread_id": "t1"}) + "\n"
        + "not json at all\n"
        + json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}) + "\n"
        + json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 4}}) + "\n"
    )
    summary, warnings = codex_package.summarise_stream(stream, "gpt-test")
    assert summary["thread_id"] == "t1"
    assert summary["non_json_lines"] == 1
    assert summary["usage_summed_over_turns"] == {"input_tokens": 3, "output_tokens": 4}
    assert summary["completed_item_types"] == {"command_execution": 1}
    assert any("not JSON" in w for w in warnings)
