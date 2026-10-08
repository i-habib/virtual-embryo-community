from __future__ import annotations

import argparse
import json
from pathlib import Path

from .html import render_comparison, render_trace
from .parsers import load_trace
from .summary import summarize


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="trace-explorer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build")
    build.add_argument("trace")
    build.add_argument("-o", "--output", type=Path, required=True)
    build.add_argument("--format", default="auto", choices=["auto", "vec-bench", "claude", "generic"])
    compare = sub.add_parser("compare")
    compare.add_argument("a")
    compare.add_argument("b")
    compare.add_argument("-o", "--output", type=Path, required=True)
    compare.add_argument("--format-a", default="auto", choices=["auto", "vec-bench", "claude", "generic"])
    compare.add_argument("--format-b", default="auto", choices=["auto", "vec-bench", "claude", "generic"])
    summary_cmd = sub.add_parser("summary")
    summary_cmd.add_argument("trace")
    summary_cmd.add_argument("--format", default="auto", choices=["auto", "vec-bench", "claude", "generic"])
    summary_cmd.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        trace = load_trace(args.trace, args.format)
        render_trace(trace, args.output)
        print(args.output)
    elif args.cmd == "compare":
        a, b = load_trace(args.a, args.format_a), load_trace(args.b, args.format_b)
        render_comparison(a, b, args.output)
        print(args.output)
    else:
        s = summarize(load_trace(args.trace, args.format))
        if args.json:
            print(json.dumps(s, indent=2, sort_keys=True))
        else:
            print(f"source: {s['source']}")
            print(f"format: {s['format']}")
            print(f"events: {s['events']}")
            if s["tasks_total"] is not None:
                print(f"tasks: {s['tasks_passed']}/{s['tasks_total']}")
            print(f"tool calls: {s['tool_calls']}")
            print(f"stderr lines: {s['stderr_lines']}")
            print(f"artifacts: {s['artifacts']}")
            if s["peak_rss_mb_max"] is not None:
                print(f"peak RSS: {s['peak_rss_mb_max']} MiB")


if __name__ == "__main__":
    main()
