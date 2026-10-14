#!/usr/bin/env python3
"""Build variants.json: sha256 of every scoring module for each veckit variant.

Usage (paths point at unpacked wheels or git worktrees; one --variant per tree):

    python make_registry.py \
        --variant pypi-0.1.0=/path/to/wheels/veckit-0.1.0-py3-none-any \
        --variant git-main-cc3859a=/path/to/worktrees/git-main-cc3859a ...

Each variant name must be a key of VARIANT_META below. Git-derived fields (head sha, commit date,
scoring files changed on the branch since its merge-base with main) are read from the worktree when the
tree is a git checkout. Only standard library is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Scoring modules: every .py file that changes what the scorer computes.
MODULE_GLOBS = ["score_h5ad.py", "veckit.py", "common/*.py", "T1/*.py", "T2/*.py", "T3/*.py"]

# Markers of the issue #7 handedness fix (PR #9, merged into main as cc3859a) in common/shape_metrics.py.
ISSUE7_MARKERS = ("np.linalg.det(Vt) < 0", "see issue #7")

# Hand-written provenance. Dates for wheels come from the orchestrator's PyPI listing (spec of 2026-10-14);
# git dates are read from the repository.
VARIANT_META = {
    "pypi-0.1.0": {"kind": "pypi", "date": "2026-08-10", "origin": "PyPI wheel veckit 0.1.0",
                   "note": "First PyPI release; scoring files identical to 0.1.1."},
    "pypi-0.1.1": {"kind": "pypi", "date": "2026-08-10", "origin": "PyPI wheel veckit 0.1.1",
                   "note": "PyPI release; scoring files identical to git 46d41e6."},
    "pypi-0.1.2": {"kind": "pypi", "date": "2026-08-25", "origin": "PyPI wheel veckit 0.1.2",
                   "note": "PyPI release; scoring files identical to unmerged PR #6 branch."},
    "git-46d41e6": {"kind": "git", "ref": "46d41e6", "origin": "github aristoteleo/veckit commit 46d41e6 (on main)",
                    "note": "Last main commit before the issue #7 fix; scoring files identical to 0.1.1."},
    "git-main-cc3859a": {"kind": "git", "ref": "cc3859a", "origin": "github aristoteleo/veckit main, merge of PR #9",
                         "note": "Main after the issue #7 fix (merge of PR #9)."},
    "pr2": {"kind": "git", "ref": "2576074", "origin": "unmerged PR #2 (6ixGODD:main)",
            "note": "Memory-safe / interruptible scoring; changes T1, common and score_h5ad.py."},
    "pr4": {"kind": "git", "ref": "dce181b", "origin": "unmerged PR #4",
            "note": "Adds T2 conformance checks; scoring files unchanged from 0.1.1."},
    "pr5": {"kind": "git", "ref": "9ad65bd", "origin": "unmerged PR #5",
            "note": "Adds adversarial control walkthrough; scoring files unchanged from 0.1.1."},
    "pr6": {"kind": "git", "ref": "22a4055", "origin": "unmerged PR #6 (branch feat/metric-hardening-0.2.0)",
            "note": "PSS/TSR scoring change, version 0.2.0; scoring files identical to PyPI 0.1.2."},
    "pr8": {"kind": "git", "ref": "17d461f", "origin": "unmerged PR #8 (perf/mmd-distance-cache)",
            "note": "Reduces MMD allocations; changes common/core_metrics.py only."},
    "pr11": {"kind": "git", "ref": "a0a5583", "origin": "unmerged PR #11 (fix/morans-exclude-self)",
             "note": "Excludes self-neighbours from Moran profiles; changes T2/metrics.py; includes issue #7 fix."},
}


def module_files(root: Path) -> list[str]:
    found: set[str] = set()
    for pattern in MODULE_GLOBS:
        for p in root.glob(pattern):
            if p.is_file():
                found.add(p.relative_to(root).as_posix())
    return sorted(found)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def git_fields(root: Path, files: list[str]) -> dict:
    head = git(root, "rev-parse", "HEAD")
    commit_date = git(root, "log", "-1", "--format=%cs", "HEAD")
    base = git(root, "merge-base", "HEAD", "main")
    changed = git(root, "diff", "--name-only", base, "HEAD", "--", *files)
    return {
        "head_sha": head,
        "commit_date": commit_date,
        "merge_base_with_main": base,
        "scoring_files_changed_since_merge_base": [f for f in changed.splitlines() if f],
    }


def build_variant(name: str, root: Path, files: list[str]) -> dict:
    meta = dict(VARIANT_META[name])
    text = {f: (root / f).read_text(encoding="utf-8", errors="replace") for f in files}
    shape = text.get("common/shape_metrics.py", "")
    entry = {
        "origin": meta["origin"],
        "date": meta.get("date", ""),
        "note": meta["note"],
        "issue7_fix": all(m in shape for m in ISSUE7_MARKERS),
        "mentions_severity_ratio_or_scale_ratio": any(
            ("severity_ratio" in t or "scale_ratio" in t) for t in text.values()),
        "module_sha256": {f: sha256(root / f) for f in files},
    }
    if meta["kind"] == "git":
        entry.update(git_fields(root, files))
        entry["date"] = entry["commit_date"]
    return entry


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", action="append", required=True, metavar="NAME=PATH")
    ap.add_argument("--out", default=str(HERE / "variants.json"))
    args = ap.parse_args()

    trees: dict[str, Path] = {}
    for item in args.variant:
        name, _, path = item.partition("=")
        if name not in VARIANT_META or not path:
            raise SystemExit(f"bad --variant {item!r}; known names: {sorted(VARIANT_META)}")
        trees[name] = Path(path).resolve()

    file_sets = {n: module_files(p) for n, p in trees.items()}
    reference = file_sets[next(iter(file_sets))]
    if any(fs != reference for fs in file_sets.values()):
        raise SystemExit("variants do not share one module file list: " +
                         json.dumps({n: fs for n, fs in file_sets.items()}, indent=1))

    variants = {}
    for name in VARIANT_META:  # fixed order from the spec
        if name in trees:
            variants[name] = build_variant(name, trees[name], reference)

    # Group variants whose scoring modules are byte-identical.
    for name, v in variants.items():
        v["identical_scoring_modules_to"] = sorted(
            other for other, w in variants.items()
            if other != name and w["module_sha256"] == v["module_sha256"])

    registry = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "module_files": reference,
        "variants": variants,
    }
    Path(args.out).write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out} with {len(variants)} variants and {len(reference)} module files")


if __name__ == "__main__":
    main()
