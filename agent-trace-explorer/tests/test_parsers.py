import json

from agent_trace_explorer.parsers import load_trace
from agent_trace_explorer.summary import summarize


def test_vec_bench_detection(tmp_path):
    p = tmp_path / "trace.jsonl"
    rows = [{"ts":"x","event":"run_start","tasks":["a"]}, {"ts":"x","event":"grade","task_id":"a","passed":True}, {"ts":"x","event":"run_end","tasks_passed":1,"tasks_total":1}]
    p.write_text("".join(json.dumps(r)+"\n" for r in rows))
    trace = load_trace(p)
    assert trace.format == "vec-bench"
    s = summarize(trace)
    assert s["tasks_passed"] == 1
    assert s["tasks_total"] == 1


def test_claude_tool_use(tmp_path):
    p = tmp_path / "claude.jsonl"
    row = {"type":"assistant", "message":{"content":[{"type":"text","text":"checking"}, {"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}
    p.write_text(json.dumps(row)+"\n")
    trace = load_trace(p)
    assert trace.format == "claude"
    assert [e.event for e in trace.events] == ["assistant_text","tool_use"]
    assert summarize(trace)["tool_calls"] == 1


def test_generic(tmp_path):
    p = tmp_path / "generic.jsonl"
    p.write_text(json.dumps({"timestamp":"x","type":"note","message":"hello"})+"\n")
    trace = load_trace(p)
    assert trace.format == "generic"
    assert trace.events[0].text == "hello"
