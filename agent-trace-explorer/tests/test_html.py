from pathlib import Path

from agent_trace_explorer.html import render_comparison, render_trace
from agent_trace_explorer.parsers import load_trace


def test_build_html():
    root = Path(__file__).parents[1] / "examples"
    a = load_trace(root / "reference.jsonl")
    b = load_trace(root / "incomplete.jsonl")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.html"
        compare = Path(tmp) / "compare.html"
        render_trace(a, report)
        render_comparison(a, b, compare)
        assert "Agent Trace Explorer" in report.read_text()
        assert "Agent Trace Comparison" in compare.read_text()
