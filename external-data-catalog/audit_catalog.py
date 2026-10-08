#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task", choices=["t1", "t2-heart", "t2-embryo", "t3"])
    p.add_argument("--include-demoted", action="store_true")
    args = p.parse_args()
    items = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    for item in items:
        if item.get("tier") == "demoted" and not args.include_demoted:
            continue
        print(f"\n{item['id']}: {item['name']}")
        print(f"  tier: {item.get('tier', 'unrated')}")
        if item.get("validation_manifest"):
            print(f"  evidence: {item['validation_manifest']}")
        print(f"  modality: {item['modality']}")
        print(f"  stages: {item['stages']}")
        if args.task:
            info = item['task_status'].get(args.task, {})
            print(f"  {args.task}: {info.get('status', 'not-rated')} — {info.get('note', '')}")
        print(f"  processor: {item['processor']}")
        print(f"  source: {item['source_url']}")


if __name__ == "__main__":
    main()
