from pathlib import Path
from agent_trace_explorer.html import render_comparison, render_trace
from agent_trace_explorer.parsers import load_trace

root = Path(__file__).parent
a = load_trace(root / "reference.jsonl")
b = load_trace(root / "incomplete.jsonl")
render_trace(a, root / "reference.html")
render_trace(b, root / "incomplete.html")
render_comparison(a, b, root / "comparison.html")
print("wrote demo HTML")
