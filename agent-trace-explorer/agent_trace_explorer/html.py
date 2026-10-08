from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .model import Trace
from .summary import summarize


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _base_css() -> str:
    return """
:root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }
body { margin: 0; background: #111; color: #eee; }
main { max-width: 1200px; margin: 0 auto; padding: 28px 20px 80px; }
h1 { margin-bottom: 6px; }
.muted { color: #aaa; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:20px 0; }
.card { border:1px solid #333; border-radius:10px; padding:12px; background:#181818; }
.card b { display:block; font-size:24px; margin-top:4px; }
.controls { display:flex; gap:10px; flex-wrap:wrap; margin:18px 0; }
input, select { background:#181818; color:#eee; border:1px solid #444; border-radius:7px; padding:8px; }
.event { border-top:1px solid #2d2d2d; padding:10px 4px; display:grid; grid-template-columns:160px 170px 160px 1fr; gap:10px; }
.event .type { font-weight:650; }
.event pre { white-space:pre-wrap; word-break:break-word; margin:0; font:12px ui-monospace,SFMono-Regular,Menlo,monospace; }
.pass { color:#82d982; } .fail, .error { color:#ff8b8b; }
table { width:100%; border-collapse:collapse; margin:16px 0 28px; }
th,td { border-bottom:1px solid #333; padding:9px; text-align:left; vertical-align:top; }
th { color:#bbb; }
@media(max-width:800px){ .event { grid-template-columns:1fr; gap:3px; } }
"""


def render_trace(trace: Trace, output: str | Path) -> None:
    summary = summarize(trace)
    payload = [{"index": e.index, "ts": e.ts, "event": e.event, "task_id": e.task_id, "text": e.text, "data": e.data} for e in trace.events]
    cards = [("Events", summary["events"]), ("Tasks", f"{summary['tasks_passed']}/{summary['tasks_total']}" if summary["tasks_total"] is not None else "—"), ("Tool calls", summary["tool_calls"]), ("stderr lines", summary["stderr_lines"]), ("Artifacts", summary["artifacts"]), ("Peak RSS", f"{summary['peak_rss_mb_max']} MiB" if summary["peak_rss_mb_max"] is not None else "—")]
    cards_html = "".join(f'<div class="card">{html.escape(k)}<b>{html.escape(str(v))}</b></div>' for k,v in cards)
    doc = f'''<!doctype html>
<meta charset="utf-8">
<title>Agent Trace Explorer</title>
<style>{_base_css()}</style>
<main>
<h1>Agent Trace Explorer</h1>
<div class="muted">{html.escape(trace.source)} · parser: {html.escape(trace.format)}</div>
<div class="cards">{cards_html}</div>
<div class="controls"><input id="search" placeholder="filter text"><select id="task"><option value="">all tasks</option></select><select id="type"><option value="">all event types</option></select></div>
<div id="events"></div>
</main>
<script>
const events = {_j(payload)};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const taskSel=document.querySelector('#task'), typeSel=document.querySelector('#type'), search=document.querySelector('#search');
[...new Set(events.map(e=>e.task_id).filter(Boolean))].sort().forEach(x=>taskSel.insertAdjacentHTML('beforeend',`<option>${{esc(x)}}</option>`));
[...new Set(events.map(e=>e.event))].sort().forEach(x=>typeSel.insertAdjacentHTML('beforeend',`<option>${{esc(x)}}</option>`));
function draw(){{ const q=search.value.toLowerCase(), task=taskSel.value, typ=typeSel.value; const rows=events.filter(e=>(!task||e.task_id===task)&&(!typ||e.event===typ)&&(!q||JSON.stringify(e).toLowerCase().includes(q))); document.querySelector('#events').innerHTML=rows.map(e=>{{ const cls=(e.event==='grade'&&e.data.passed===true)?'pass':((e.event==='grade'&&e.data.passed===false)||e.event.includes('stderr')?'fail':''); const body=e.text ?? ((e.event==='grade')?JSON.stringify(e.data.checks??[]):''); return `<div class="event"><div class="muted">${{esc(e.ts??'')}}</div><div>${{esc(e.task_id??'')}}</div><div class="type ${{cls}}">${{esc(e.event)}}</div><pre>${{esc(body)}}</pre></div>`; }}).join(''); }}
[search,taskSel,typeSel].forEach(x=>x.addEventListener('input',draw)); draw();
</script>
'''
    Path(output).write_text(doc, encoding="utf-8")


def render_comparison(a: Trace, b: Trace, output: str | Path) -> None:
    sa, sb = summarize(a), summarize(b)
    keys = ["events","tasks_passed","tasks_total","tool_calls","stderr_lines","artifacts","duration_seconds_total","peak_rss_mb_max"]
    rows = "".join(f"<tr><th>{html.escape(k.replace('_',' '))}</th><td>{html.escape(str(sa.get(k)))}</td><td>{html.escape(str(sb.get(k)))}</td></tr>" for k in keys)
    tasks = sorted(set(sa["task_grades"]) | set(sb["task_grades"]))
    task_rows = "".join(f"<tr><th>{html.escape(t)}</th><td>{'PASS' if sa['task_grades'].get(t) else ('FAIL' if t in sa['task_grades'] else '—')}</td><td>{'PASS' if sb['task_grades'].get(t) else ('FAIL' if t in sb['task_grades'] else '—')}</td></tr>" for t in tasks)
    doc=f'''<!doctype html><meta charset="utf-8"><title>Agent Trace Comparison</title><style>{_base_css()}</style><main><h1>Agent Trace Comparison</h1><table><thead><tr><th></th><th>{html.escape(a.source)}</th><th>{html.escape(b.source)}</th></tr></thead><tbody>{rows}</tbody></table><h2>Task grades</h2><table><thead><tr><th>Task</th><th>A</th><th>B</th></tr></thead><tbody>{task_rows}</tbody></table><p class="muted">This report compares recorded behavior. It does not decide which scientific result is better.</p></main>'''
    Path(output).write_text(doc, encoding="utf-8")
