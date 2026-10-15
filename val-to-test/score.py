#!/usr/bin/env python3
"""Score every candidate (and the split-half ceiling) on every pair and seed, caching each result.

    python score.py --config configs/heart_now.json [--stage-dir DIR] [--pairs val,test] [--candidates NAME,...]

One worker subprocess per (pair, candidate, seed). Each finished job is appended to results/scores.jsonl
at once, so an interrupted run resumes: jobs whose key is already in the file are skipped. A key covers
the config name, the pair signature, the pair, the candidate and the seed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from config import CEILING, ConfigError, load_config, pair_signature  # noqa: E402
from methods import candidates  # noqa: E402


def veckit_commit() -> str:
    try:
        info = json.loads(metadata.distribution("veckit").read_text("direct_url.json") or "{}")
        return info.get("vcs_info", {}).get("commit_id", "unknown")[:7]
    except Exception:
        return "unknown"


def load_cache(path: Path) -> dict:
    cache = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                cache[rec["key"]] = rec
    return cache


def job_key(config: str, sig: str, pair: str, cand: str, seed: int) -> str:
    return f"{config}|{sig}|{pair}|{cand}|{seed}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--work-dir", type=Path)
    ap.add_argument("--results", type=Path, default=HERE / "results" / "scores.jsonl")
    ap.add_argument("--pairs", help="comma-separated subset of pair names")
    ap.add_argument("--candidates", help="comma-separated subset of candidate names (ceiling is always included)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    work = args.work_dir or HERE / "work" / cfg["name"]
    if not (work / "manifest.json").exists():
        raise ConfigError(f"no prepared stages in {work}; run prepare.py first")

    pairs = args.pairs.split(",") if args.pairs else list(cfg["pairs"])
    names = [c.name for c in candidates()]
    if args.candidates:
        wanted = args.candidates.split(",")
        names = [n for n in names if n in wanted]
    families = {c.name: c.family for c in candidates()}
    names = names + [CEILING]
    cache = load_cache(args.results)
    args.results.parent.mkdir(parents=True, exist_ok=True)
    version = veckit_commit()

    total = len(pairs) * len(names) * len(cfg["seeds"])
    done = 0
    for pair in pairs:
        sig = pair_signature(cfg, pair)
        p = cfg["pairs"][pair]
        for cand in names:
            family = "ceiling" if cand == CEILING else families[cand]
            for seed in cfg["seeds"]:
                done += 1
                key = job_key(cfg["name"], sig, pair, cand, seed)
                if key in cache:
                    continue
                cmd = [sys.executable, str(HERE / "worker.py"), "--config", str(args.config.resolve()),
                       "--work-dir", str(work), "--pair", pair, "--candidate", cand, "--seed", str(seed)]
                proc = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
                if proc.returncode != 0:
                    sys.stderr.write(proc.stderr[-3000:])
                    raise SystemExit(f"job failed: {pair} {cand} seed={seed}")
                res = json.loads(proc.stdout.strip().splitlines()[-1])
                rec = {
                    "key": key, "config": cfg["name"], "signature": sig, "pair": pair,
                    "candidate": cand, "family": family, "seed": seed,
                    "task": p["task"], "setting": p["setting"], "board": p["board"],
                    "inputs": p["inputs"], "target": p["target"], "veckit": version,
                    "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    **res,
                }
                with open(args.results, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                cache[key] = rec
                print(f"[{done}/{total}] {pair} {cand} seed={seed} "
                      f"{res['seconds']}s fp={res['fingerprint']}", flush=True)
    print(f"done: {len(cache)} cached records in {args.results}")


if __name__ == "__main__":
    main()
