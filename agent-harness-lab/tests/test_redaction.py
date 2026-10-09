"""Secrets in the command template or argv must not reach trace.jsonl."""

import json
import sys

from vec_agent_bench.runner import run_benchmark
from vec_agent_bench.util import redact_argv, redact_text

SECRET = "sk-test-SECRET123456"


def test_redact_text_masks_flag_values_and_assignments():
    assert redact_text(f"my-agent --api-key {SECRET} --prompt {{prompt}}") == "my-agent --api-key <redacted> --prompt {prompt}"
    assert redact_text(f"my-agent --api-key={SECRET}") == "my-agent --api-key=<redacted>"
    assert redact_text("OPENAI_API_KEY=abc123 python x.py") == "OPENAI_API_KEY=<redacted> python x.py"
    assert redact_text("--token=abc123 --password hunter2") == "--token=<redacted> --password <redacted>"
    assert redact_text('curl -H "Authorization: Bearer abc.def" x') == 'curl -H "Authorization: Bearer <redacted> x'
    assert redact_text(f"bare {SECRET} here") == "bare <redacted> here"


def test_redact_argv_masks_value_after_secret_flag():
    argv = ["my-agent", "--api-key", SECRET, "--prompt", "say hi"]
    assert redact_argv(argv) == ["my-agent", "--api-key", "<redacted>", "--prompt", "say hi"]


def test_redaction_leaves_ordinary_text_alone():
    prompt = "Write answer.json with exactly these keys: `n_cells`, `n_genes`. Use each label once."
    assert redact_text(prompt) == prompt
    assert redact_text("my-agent --max-tokens 100 --keyword x") == "my-agent --max-tokens 100 --keyword x"
    assert redact_argv(["agent", "--prompt", prompt]) == ["agent", "--prompt", prompt]


def test_trace_does_not_contain_inline_secret(tmp_path):
    command = f"{sys.executable} -c pass --api-key {SECRET}"
    out = tmp_path / "run"
    summary = run_benchmark(command, ["inspect_h5ad"], out, timeout_seconds=60)
    assert summary["tasks_total"] == 1
    trace_text = (out / "trace.jsonl").read_text(encoding="utf-8")
    assert SECRET not in trace_text
    rows = [json.loads(line) for line in trace_text.splitlines()]
    run_start = next(r for r in rows if r["event"] == "run_start")
    task_start = next(r for r in rows if r["event"] == "task_start")
    assert "<redacted>" in run_start["command_template"]
    assert task_start["argv"][-1] == "<redacted>"
