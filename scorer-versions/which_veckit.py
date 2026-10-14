#!/usr/bin/env python3
"""Identify which veckit scorer is installed in the current Python environment.

Finds the installed veckit scoring modules without importing them, hashes them, and compares the hashes
with variants.json (built by make_registry.py). Standard library only.

    python which_veckit.py                 # uses the interpreter that runs this script
    python which_veckit.py --root DIR      # inspect a tree directly (e.g. an unpacked wheel)

Exit codes: 0 known variant, 1 unknown or modified scorer, 2 veckit not found.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY_PATH = HERE / "variants.json"
EVALUATION_URL = "https://virtualembryo.ai/challenge/evaluation"

def find_installed_root() -> Path | None:
    """Directory holding the top-level veckit modules, found without importing them."""
    spec = importlib.util.find_spec("veckit")
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).resolve().parent


def scoring_files(root: Path, module_files: list[str]) -> tuple[list[str], list[str]]:
    """Return (present expected files, expected files that are missing) under root."""
    present = [f for f in module_files if (root / f).is_file()]
    missing = [f for f in module_files if f not in present]
    return present, missing


def unexpected_files(root: Path, module_files: list[str]) -> list[str]:
    """Scoring-module-shaped .py files under root that the registry does not know about."""
    known = set(module_files)
    found = set()
    for pattern in ("score_h5ad.py", "veckit.py", "common/*.py", "T1/*.py", "T2/*.py", "T3/*.py"):
        for p in root.glob(pattern):
            if p.is_file():
                found.add(p.relative_to(root).as_posix())
    return sorted(found - known)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_tree(root: Path, module_files: list[str]) -> dict[str, str]:
    present, _ = scoring_files(root, module_files)
    return {f: sha256(root / f) for f in present}


def identify(root: Path, registry: dict) -> dict:
    """Compare the scoring modules under `root` with every variant in `registry`."""
    module_files = registry["module_files"]
    variants = registry["variants"]
    installed = hash_tree(root, module_files)
    _, missing = scoring_files(root, module_files)
    extra = unexpected_files(root, module_files)

    exact = []
    diffs = {}
    for name, v in variants.items():
        expected = v["module_sha256"]
        differing = sorted(f for f in set(expected) | set(installed)
                           if expected.get(f) != installed.get(f))
        diffs[name] = differing
        if not differing:
            exact.append(name)

    result = {"root": str(root), "missing_files": missing, "unexpected_files": extra,
              "matches": exact, "answer": None, "ambiguous": [], "closest": None, "warnings": [], "ok": False}

    if exact:
        result["ok"] = True
        released = [n for n in exact if not is_unmerged(variants[n])]
        pool = released if released else exact
        if len(pool) == 1:
            result["answer"] = pool[0]
        else:
            result["ambiguous"] = pool
        candidates = exact
    else:
        closest = min(variants, key=lambda n: (len(diffs[n]), n))
        result["closest"] = {"variant": closest, "differing_files": diffs[closest]}
        candidates = [closest]

    result["warnings"] = warnings_for(root, candidates, variants)
    return result


def is_unmerged(variant: dict) -> bool:
    return "unmerged" in variant.get("origin", "")


def warnings_for(root: Path, candidates: list[str], variants: dict) -> list[str]:
    """Plain-language warnings for the matched variants (or the closest variant for an unknown tree)."""
    warn = []
    no_fix = [n for n in candidates if not variants[n].get("issue7_fix")]
    if no_fix:
        warn.append("lacks the issue #7 fix (right-handed PCA frame in common/shape_metrics.py; merged into "
                    f"main as cc3859a): {', '.join(no_fix)}")
    prs = [n for n in candidates if is_unmerged(variants[n])]
    if prs:
        warn.append("scoring modules are byte-identical to an unmerged PR branch, which is not on main: "
                    f"{', '.join(prs)}")
    if _tree_mentions(root, ("severity_ratio", "scale_ratio")):
        warn.append("reports severity_ratio and/or scale_ratio, which the leaderboard does not rank. The board "
                    "contract (panels/index.json) anchors severity_slope and scale_log_ratio, and the evaluation page "
                    f"({EVALUATION_URL}, Task 3 > Scoring) names common/core_metrics.py::severity_slope. This "
                    "version's own comments call the ratios 'what ranks'; ignore those columns when comparing with "
                    "the board")
    return warn


def _tree_mentions(root: Path, needles: tuple[str, ...]) -> bool:
    """Search only veckit's own scoring modules: veckit installs flat into site-packages."""
    files = [root / "score_h5ad.py", root / "veckit.py"]
    for pkg in ("common", "T1", "T2", "T3"):
        files += sorted((root / pkg).glob("*.py"))
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(n in text for n in needles):
            return True
    return False


def load_registry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render(res: dict, registry: dict) -> str:
    variants = registry["variants"]
    lines = [f"veckit tree: {res['root']}"]
    if res["missing_files"]:
        lines.append(f"missing scoring files: {', '.join(res['missing_files'])}")
    if res["unexpected_files"]:
        lines.append(f"unexpected scoring files: {', '.join(res['unexpected_files'])}")
    if res["answer"]:
        name = res["answer"]
        v = variants[name]
        lines.append(f"result: {name}")
        others = [n for n in res["matches"] if n != name]
        if others:
            lines.append(f"byte-identical scoring modules also in: {', '.join(others)}")
        lines.append(f"origin: {v['origin']} ({v['date']})")
        lines.append(f"note: {v['note']}")
    elif res["ok"]:
        lines.append("result: ambiguous; these variants have byte-identical scoring modules and cannot be told apart: "
                     + ", ".join(res["ambiguous"]))
        others = [n for n in res["matches"] if n not in res["ambiguous"]]
        if others:
            lines.append(f"also byte-identical to: {', '.join(others)}")
    else:
        c = res["closest"]
        lines.append("result: unknown/modified scorer")
        lines.append(f"closest variant: {c['variant']}; files that differ: {', '.join(c['differing_files'])}")
    for w in res["warnings"]:
        lines.append(f"WARNING: {w}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, help="inspect this directory instead of the installed veckit")
    ap.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    args = ap.parse_args()

    registry = load_registry(args.registry)
    root = args.root.resolve() if args.root else find_installed_root()
    if root is None or not root.is_dir():
        print("veckit is not importable from this interpreter (" + sys.executable + ")", file=sys.stderr)
        return 2
    res = identify(root, registry)
    print(f"python: {sys.executable}")
    print(render(res, registry))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
