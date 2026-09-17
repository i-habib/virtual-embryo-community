#!/usr/bin/env python3
"""Render a small external-source registry into a method-summary disclosure section."""
from __future__ import annotations
import argparse, json
from pathlib import Path

FIELDS = ["name", "url", "version", "license", "tasks", "stages_or_conditions", "used_for", "filters"]

def render(items):
    out = ["## External data, pretrained models, and published code", ""]
    if not items:
        out.append("No external sources recorded.")
        return "\n".join(out) + "\n"
    for i, item in enumerate(items, 1):
        missing = [f for f in FIELDS if f not in item]
        if missing:
            raise ValueError(f"Entry {i} is missing fields: {', '.join(missing)}")
        tasks = ", ".join(item["tasks"]) if isinstance(item["tasks"], list) else item["tasks"]
        out += [
            f"### {i}. {item['name']}", "",
            f"- Source: {item['url']}",
            f"- Version / access identifier: {item['version']}",
            f"- License / terms: {item['license']}",
            f"- Task(s): {tasks}",
            f"- Stages / conditions present: {item['stages_or_conditions']}",
            f"- How it entered the method: {item['used_for']}",
            f"- Filtering applied for challenge eligibility: {item['filters']}",
        ]
        if item.get("notes"):
            out.append(f"- Notes: {item['notes']}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("registry", type=Path)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    items = json.loads(args.registry.read_text(encoding="utf-8"))
    text = render(items)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text, end="")

if __name__ == "__main__":
    main()
