#!/usr/bin/env python3
"""Rescore a submission history locally once the validation answers are released.

Inputs: a submissions.csv (made by export_submissions.js), a boards.json that points at the released
files, the folders that hold the submitted files, and the public panel index. Outputs: one local score
per submitted file and board, a comparison with the board's own score, and a Markdown summary.

A local rescoring is an analysis of files you already submitted. It is not a score.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import numbers
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Headline formula, weights and metric directions live in metric-lens; import them, do not copy.
sys.path.insert(0, str(HERE.parent / "metric-lens"))
import vec_metric_lens as ml  # noqa: E402

INDEX_URL = "https://virtualembryo.ai/challenge/panels/index.json"
SUBMISSION_COLUMNS = ["submitted", "task", "file", "board", "board_score"]
DEFAULT_FRACTION = 0.1  # the stage subsample rate used by the board protocol
PROTOCOLS = ("board", "full")

WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"WARNING: {msg}", file=sys.stderr)


class WorkerError(RuntimeError):
    """A scoring or subsampling subprocess failed."""


# --------------------------------------------------------------------------------------------------
# Hashing and small helpers
# --------------------------------------------------------------------------------------------------

_SHA_CACHE: dict[tuple[str, int, int], str] = {}


def sha256_file(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _SHA_CACHE:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _SHA_CACHE[key] = h.hexdigest()
    return _SHA_CACHE[key]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _finite(x) -> bool:
    return isinstance(x, numbers.Real) and not isinstance(x, bool) and math.isfinite(float(x))


def mean_or_none(xs):
    xs = [float(x) for x in xs if _finite(x)]
    return sum(xs) / len(xs) if xs else None


def sd_or_none(xs):
    xs = [float(x) for x in xs if _finite(x)]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def average_ranks(values: list[float]) -> list[float]:
    """1-based ranks with ties given their average rank (the convention used by Spearman)."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x, y) -> tuple[float | None, int]:
    """Spearman rho over pairs where both values are finite. Returns (rho or None, n)."""
    pairs = [(float(a), float(b)) for a, b in zip(x, y) if _finite(a) and _finite(b)]
    n = len(pairs)
    if n < 3:
        return None, n
    rx = average_ranks([p[0] for p in pairs])
    ry = average_ranks([p[1] for p in pairs])
    mx = sum(rx) / n
    my = sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None, n
    return sxy / math.sqrt(sxx * syy), n


def parse_float(text) -> float | None:
    if text is None:
        return None
    s = str(text).strip().replace(",", "")
    if s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


# --------------------------------------------------------------------------------------------------
# Board guessing (mirrors export_submissions.js; the tests check both against one table)
# --------------------------------------------------------------------------------------------------

def normalise_task(task: str) -> str:
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", task or "").split()).lower()


def guess_board(task: str, file_name: str) -> str:
    """Return a board key, or "" when the row must be set by hand."""
    t = normalise_task(task)
    f = file_name or ""
    if re.match(r"^t1\b", t):
        return "T1:val"
    if re.match(r"^t3\b", t):
        return "T3:gata4"
    if re.match(r"^t2 embryo\b", t):
        return "T2:embryo:val_interp"
    if re.match(r"^t2 heart\b", t):
        interp = bool(re.search(r"E8\.5|interp", f, re.I))
        extrap = bool(re.search(r"E10\.5|extrap", f, re.I))
        if interp and not extrap:
            return "T2:heart:val_interp"
        if extrap and not interp:
            return "T2:heart:val_extrap"
    return ""


# --------------------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------------------

def read_submissions(path: Path, guess_blank: bool = False) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        missing = [c for c in SUBMISSION_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"{path} lacks column(s) {missing}; expected {SUBMISSION_COLUMNS}")
        rows = []
        for line_no, r in enumerate(reader, start=2):
            task = (r.get("task") or "").strip()
            file_name = (r.get("file") or "").strip()
            board = (r.get("board") or "").strip()
            if not board and guess_blank:
                board = guess_board(task, file_name)
                if board:
                    warn(f"line {line_no}: board guessed as {board} for {file_name}; check it by hand")
            rows.append({
                "line": line_no,
                "submitted": (r.get("submitted") or "").strip(),
                "task": task,
                "file": file_name,
                "board": board,
                "board_score": parse_float(r.get("board_score")),
                "board_score_text": (r.get("board_score") or "").strip(),
            })
    return rows


def read_validator(path: Path | None) -> dict[tuple[str, str], float]:
    if path is None:
        return {}
    out: dict[tuple[str, str], float] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in ("file", "board", "value") if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} lacks column(s) {missing}; expected file,board,value")
        for r in reader:
            v = parse_float(r.get("value"))
            if v is not None:
                out[((r["file"] or "").strip(), (r["board"] or "").strip())] = v
    return out


def _resolve_path(base: Path, p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else (base / q).resolve()


def load_boards(path: Path) -> dict[str, dict]:
    base = path.resolve().parent
    raw = json.loads(path.read_text(encoding="utf-8"))
    boards: dict[str, dict] = {}
    for key, cfg in raw.items():
        if key.startswith("_"):
            continue
        task = key.split(":")[0]
        if task not in ("T1", "T2", "T3"):
            raise ValueError(f"boards.json: unknown task in key {key!r}")
        reference = cfg.get("reference") or cfg.get("wt")
        if not cfg.get("target") or not reference:
            raise ValueError(f"boards.json: {key} needs 'target' and 'reference' (or 'wt' for T3)")
        setting = cfg.get("setting") or (key.split(":")[1] if task == "T2" else None)
        if task == "T2" and setting not in ("heart", "embryo"):
            raise ValueError(f"boards.json: {key} needs setting 'heart' or 'embryo'")
        fraction = float(cfg.get("fraction", DEFAULT_FRACTION))
        if not 0 < fraction <= 1:
            raise ValueError(f"boards.json: {key} fraction must be in (0, 1]")
        boards[key] = {
            "task": task,
            "setting": setting,
            "target": _resolve_path(base, cfg["target"]),
            "reference": _resolve_path(base, reference),
            "fraction": fraction,
            "target_is_working_copy": bool(cfg.get("target_is_working_copy", False)),
            "reference_is_working_copy": bool(cfg.get("reference_is_working_copy", False)),
            "weights_from": cfg.get("weights_from"),
            "synthetic": bool(cfg.get("synthetic", False)),
        }
    return boards


def load_index(path: str | None, out_dir: Path) -> tuple[dict, str, str]:
    if path:
        data = Path(path).read_bytes()
        source = str(path)
    else:
        with urllib.request.urlopen(INDEX_URL, timeout=60) as resp:
            data = resp.read()
        source = INDEX_URL
    (out_dir / "index_used.json").write_bytes(data)
    return json.loads(data), source, hashlib.sha256(data).hexdigest()


def _kind(split: str | None) -> str | None:
    s = split or ""
    if "extrap" in s:
        return "extrap"
    if "interp" in s:
        return "interp"
    return None


def weights_key_for(board: str, entry: dict, cfg: dict) -> str:
    """Which metric-lens board supplies weights and directions for this board.

    Exact key first. Otherwise match on task, setting (T2 embryo/heart, T3 target) and interp/extrap,
    so that a test-phase board with the same design reuses the validation weights. Ambiguous or no
    match is an error: set "weights_from" in boards.json.
    """
    if cfg.get("weights_from"):
        return cfg["weights_from"]
    if board in ml.BOARDS:
        return board
    setting = entry.get("setting") or entry.get("target_ko")
    kind = _kind(entry.get("split"))
    matches = []
    for key in ml.BOARDS:
        parts = key.split(":")
        if parts[0] != entry.get("task"):
            continue
        k_setting = parts[1] if parts[0] in ("T2", "T3") else None
        if k_setting == setting and _kind(parts[-1]) == kind:
            matches.append(key)
    if len(matches) != 1:
        raise ValueError(
            f"no metric-lens weights for {board} (matches: {matches}); set 'weights_from' in boards.json"
        )
    return matches[0]


def anchor_drift(entry: dict, weights_key: str) -> list[str]:
    """Metrics whose index anchors differ from the copy in metric-lens (only checked for known boards)."""
    if weights_key not in ml.BOARDS:
        return []
    drift = []
    for name, mspec in ml.BOARDS[weights_key]["metrics"].items():
        a = entry["anchors"].get(name)
        if a is None:
            continue
        if not (math.isclose(a["floor"], mspec["floor"], rel_tol=0, abs_tol=1e-12)
                and math.isclose(a["ceiling"], mspec["ceiling"], rel_tol=0, abs_tol=1e-12)):
            drift.append(name)
    return drift


# --------------------------------------------------------------------------------------------------
# Headline (metric-lens formula, index anchors)
# --------------------------------------------------------------------------------------------------

def board_headline(metrics: dict, entry: dict, weights_key: str) -> dict:
    """Headline = 100 * sum(weight * skill), skill from metric_skill() with the index's anchors."""
    spec_all = ml.BOARDS[weights_key]["metrics"]
    missing = [m for m in spec_all if m not in entry["anchors"]]
    if missing:
        raise ValueError(f"index entry lacks anchors for {missing}")
    total = 0.0
    skills, raws = {}, {}
    for name, mspec in spec_all.items():
        a = entry["anchors"][name]
        spec = dict(mspec, floor=a["floor"], ceiling=a["ceiling"])
        raw = metrics.get(name)
        skill = ml.metric_skill(raw, spec)
        skills[name] = skill
        raws[name] = raw if _finite(raw) else None
        total += 100.0 * mspec["weight"] * skill
    return {"headline": total, "skills": skills, "raw": raws}


# --------------------------------------------------------------------------------------------------
# Finding submitted files by name
# --------------------------------------------------------------------------------------------------

@dataclass
class Resolution:
    name: str
    path: Path | None
    sha: str | None
    status: str  # "found", "found_identical_copies", "ambiguous_newest", "missing"
    candidates: list[Path] = field(default_factory=list)
    note: str = ""


def _is_under(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def resolve_files(names: list[str], search_dirs: list[Path], prefer_dirs: list[Path]) -> dict[str, Resolution]:
    wanted = set(names)
    found: dict[str, list[Path]] = {n: [] for n in names}
    for d in search_dirs:
        for root, dirs, files in os.walk(d):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for f in files:
                if f in wanted:
                    found[f].append(Path(root) / f)
    out: dict[str, Resolution] = {}
    for name in names:
        cands = sorted(found[name])
        if not name:
            out[name] = Resolution(name, None, None, "missing", note="blank file name")
            continue
        if not cands:
            out[name] = Resolution(name, None, None, "missing", note="not found under the search folders")
            continue
        if len(cands) == 1:
            out[name] = Resolution(name, cands[0], sha256_file(cands[0]), "found", cands)
            continue
        shas = {str(p): sha256_file(p) for p in cands}
        if len(set(shas.values())) == 1:
            out[name] = Resolution(name, cands[0], shas[str(cands[0])], "found_identical_copies", cands,
                                   note=f"{len(cands)} identical copies")
            continue
        preferred = [p for p in cands if any(_is_under(p, d) for d in prefer_dirs)]
        if len(preferred) == 1:
            p = preferred[0]
            out[name] = Resolution(name, p, shas[str(p)], "found", cands, note="chosen by --prefer")
            continue
        newest = max(cands, key=lambda p: p.stat().st_mtime_ns)
        note = "different files share this name: " + "; ".join(str(p) for p in cands) + \
            f"; newest used ({newest}); pass --prefer DIR to choose"
        out[name] = Resolution(name, newest, shas[str(newest)], "ambiguous_newest", cands, note=note)
        warn(f"{name}: {note}")
    return out


# --------------------------------------------------------------------------------------------------
# Scorer protocol
# --------------------------------------------------------------------------------------------------

def subsample_h5ad(src: Path, dst: Path, *, fraction: float, seed: int, stream: int, half: bool = False) -> dict:
    """Keep round(fraction * n) cells drawn without replacement with a seeded RNG.

    stream separates the target and reference draws. half=True keeps the first half of the kept cells in a
    second seeded permutation, which is the "half A" the board scores against.
    """
    import anndata as ad
    import numpy as np

    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    a = ad.read_h5ad(src)
    n = int(a.n_obs)
    k = max(1, int(round(fraction * n)))
    keep = np.sort(np.random.default_rng([int(seed), int(stream)]).choice(n, size=k, replace=False))
    if half:
        perm = np.random.default_rng([int(seed), 2]).permutation(k)[: k // 2]
        keep = keep[np.sort(perm)]
    b = a[keep].copy()
    b.write_h5ad(dst)
    return {"n_source": n, "n_after_fraction": k, "n_written": int(b.n_obs)}


def _peak_rss_mb() -> float:
    import resource

    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / (1024 * 1024) if sys.platform == "darwin" else r / 1024


def score_file(spec: dict) -> dict:
    """Runs inside a worker subprocess so the main process never loads veckit or a large matrix."""
    from veckit import score  # noqa: WPS433  (imported here on purpose)

    kwargs: dict = {"seed": int(spec["seed"])}
    if spec["task"] == "T2":
        kwargs["setting"] = spec["setting"]
    if spec["task"] == "T3":
        kwargs["wt"] = spec["reference"]
    else:
        kwargs["reference"] = spec["reference"]
    res = score(task=spec["task"], input=spec["input"], target=spec["target"], **kwargs)
    metrics = {}
    for k, v in res["metrics"].items():
        if k.startswith("_") or isinstance(v, bool) or not isinstance(v, numbers.Real):
            continue
        metrics[k] = float(v)
    return {"metrics": metrics, "meta": json.loads(json.dumps(res["meta"], default=str)),
            "peak_rss_mb": _peak_rss_mb()}


def worker_main(spec_path: str) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    if spec["op"] == "subsample":
        result = subsample_h5ad(Path(spec["src"]), Path(spec["out"]), fraction=float(spec["fraction"]),
                                seed=int(spec["seed"]), stream=int(spec["stream"]), half=bool(spec["half"]))
    elif spec["op"] == "score":
        result = score_file(spec)
    else:
        raise ValueError(f"unknown worker op {spec['op']!r}")
    Path(spec["result_path"]).write_text(json.dumps(result), encoding="utf-8")


def run_worker(spec: dict) -> dict:
    """Run one scoring or subsampling job in a fresh Python process (bounded memory, one file at a time)."""
    result_path = Path(spec["result_path"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path = result_path.with_name(result_path.stem + ".spec.json")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--_worker", str(spec_path)],
        capture_output=True, text=True,
    )
    spec_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise WorkerError(lines[-1] if lines else f"worker exit code {proc.returncode}")
    data = json.loads(result_path.read_text(encoding="utf-8"))
    result_path.unlink(missing_ok=True)
    return data


def ensure_working(board: str, cfg: dict, seed: int, work_root: Path) -> tuple[Path, Path, dict]:
    """Board protocol: the 10% working copy of the reference, and half A of the 10% target."""
    d = work_root / board.replace(":", "__") / f"seed{seed}"
    tgt = d / "target_halfA.h5ad"
    ref = d / "reference_working.h5ad"
    man = d / "manifest.json"
    # A release that is already a working copy is not subsampled again.
    frac_ref = 1.0 if cfg["reference_is_working_copy"] else cfg["fraction"]
    frac_tgt = 1.0 if cfg["target_is_working_copy"] else cfg["fraction"]
    want = {"target_sha": cfg["target_sha"], "reference_sha": cfg["reference_sha"],
            "fraction_target": frac_tgt, "fraction_reference": frac_ref, "seed": seed}
    if man.exists() and tgt.exists() and ref.exists():
        try:
            saved = json.loads(man.read_text(encoding="utf-8"))
            if saved.get("want") == want:
                return tgt, ref, saved
        except (json.JSONDecodeError, OSError):
            pass
    d.mkdir(parents=True, exist_ok=True)
    info_ref = run_worker({"op": "subsample", "src": str(cfg["reference"]), "out": str(ref),
                           "fraction": frac_ref, "seed": seed, "stream": 1, "half": False,
                           "result_path": str(d / "ref_result.json")})
    info_tgt = run_worker({"op": "subsample", "src": str(cfg["target"]), "out": str(tgt),
                           "fraction": frac_tgt, "seed": seed, "stream": 0, "half": True,
                           "result_path": str(d / "tgt_result.json")})
    saved = {"want": want, "reference": info_ref, "target": info_tgt}
    man.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    return tgt, ref, saved


def scorer_signature() -> str:
    """Hash of the installed veckit's Python sources, so cached scores are tied to one scorer build."""
    spec = importlib.util.find_spec("score_h5ad")
    if spec is None or spec.origin is None:
        raise RuntimeError("veckit is not installed in this Python environment (pip install veckit from git)")
    root = Path(spec.origin).parent
    files = [root / "score_h5ad.py", root / "veckit.py"]
    for pkg in ("T1", "T2", "T3", "common"):
        if (root / pkg).is_dir():
            files += sorted((root / pkg).rglob("*.py"))
    h = hashlib.sha256()
    for f in files:
        if f.exists():
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def veckit_version() -> str:
    try:
        return importlib.metadata.version("veckit")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# --------------------------------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------------------------------

def load_cache(path: Path) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if not path.exists():
        return cache
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            cache[rec["key"]] = rec
        except (json.JSONDecodeError, KeyError):
            warn(f"skipping malformed line {i} in {path}")
    return cache


def append_cache(path: Path, rec: dict) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------------------------------
# Main pipeline
# --------------------------------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--submissions", required=True, type=Path, help="submissions.csv from export_submissions.js")
    ap.add_argument("--search", required=True, nargs="+", type=Path, help="folders to search for submitted files")
    ap.add_argument("--boards", required=True, type=Path, help="boards.json: board key -> released files")
    ap.add_argument("--index", help="panels index.json (default: download the live copy)")
    ap.add_argument("--protocol", choices=PROTOCOLS, default="board",
                    help="board: evaluation-page protocol (10%% subsample, half A); full: whole released target")
    ap.add_argument("--seeds", type=int, default=3, help="number of seeds, 0..N-1 (default 3)")
    ap.add_argument("--out", type=Path, default=Path("results"), help="output folder (default results/)")
    ap.add_argument("--prefer", action="append", type=Path, default=[],
                    help="folder that wins when two different files share a name (repeatable)")
    ap.add_argument("--local-validator", type=Path, dest="validator",
                    help="optional CSV with columns file,board,value to compare with board and local scores")
    ap.add_argument("--guess-blank", action="store_true",
                    help="fill blank board cells with the export rules; check the guesses by hand")
    ap.add_argument("--keep-work", action="store_true", help="keep derived working copies in out/work/")
    return ap.parse_args(argv)


def _metric_order(board_keys_weights: list[str]) -> list[str]:
    names: list[str] = []
    for wk in board_keys_weights:
        for m in ml.BOARDS[wk]["metrics"]:
            if m not in names:
                names.append(m)
    return names


def main(argv=None) -> int:
    WARNINGS.clear()
    args = parse_args(argv)
    if args.seeds < 1:
        raise SystemExit("--seeds must be at least 1")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    rows = read_submissions(args.submissions, guess_blank=args.guess_blank)
    boards = load_boards(args.boards)
    for key, cfg in boards.items():
        for label in ("target", "reference"):
            if not cfg[label].exists():
                raise SystemExit(f"released file missing for {key} ({label}): {cfg[label]}")
    for d in args.search:
        if not d.is_dir():
            warn(f"search folder does not exist: {d}")
    validator = read_validator(args.validator)

    index, index_source, index_sha = load_index(str(args.index) if args.index else None, out)
    scorer_sig = scorer_signature()
    vk_version = veckit_version()

    for key, cfg in boards.items():
        if key not in index:
            raise SystemExit(f"{key} is in boards.json but not in the panel index")
        entry = index[key]
        cfg["entry"] = entry
        cfg["weights_key"] = weights_key_for(key, entry, cfg)
        drift = anchor_drift(entry, cfg["weights_key"])
        if drift:
            warn(f"{key}: index anchors differ from metric-lens for {drift}; the index is used")
        cfg["target_sha"] = sha256_file(cfg["target"])
        cfg["reference_sha"] = sha256_file(cfg["reference"])
        cfg["board_sig"] = sha256_text(json.dumps({
            "target": cfg["target_sha"], "reference": cfg["reference_sha"], "fraction": cfg["fraction"],
            "target_is_working_copy": cfg["target_is_working_copy"],
            "reference_is_working_copy": cfg["reference_is_working_copy"],
            "protocol": args.protocol, "setting": cfg["setting"], "scorer": scorer_sig,
        }, sort_keys=True))

    names = sorted({r["file"] for r in rows})
    resolved = resolve_files(names, args.search, args.prefer)

    cache_path = out / "scores.jsonl"
    cache = load_cache(cache_path)
    work_root = out / "work"
    pair_cache: dict[tuple[str, str], dict] = {}
    worker_calls = 0

    def score_pair(file_name: str, board: str) -> dict:
        nonlocal worker_calls
        res = resolved[file_name]
        cfg = boards[board]
        recs = []
        for seed in range(args.seeds):
            key = "|".join([res.sha, board, args.protocol, str(seed), cfg["board_sig"]])
            if key in cache:
                recs.append(cache[key])
                continue
            if args.protocol == "board":
                tgt, ref, _ = ensure_working(board, cfg, seed, work_root)
            else:
                tgt, ref = cfg["target"], cfg["reference"]
            spec = {"op": "score", "task": cfg["task"], "setting": cfg["setting"],
                    "input": str(res.path), "target": str(tgt), "reference": str(ref), "seed": seed,
                    "result_path": str(work_root / "_scratch" / f"score_{res.sha[:12]}_{board.replace(':', '_')}_{seed}.json")}
            worker_calls += 1
            print(f"scoring {file_name} | {board} | {args.protocol} | seed {seed}", file=sys.stderr)
            data = run_worker(spec)
            rec = {"key": key, "file": file_name, "file_sha256": res.sha, "board": board,
                   "protocol": args.protocol, "seed": seed, "board_sig": cfg["board_sig"],
                   "veckit": vk_version, "scorer_sig": scorer_sig,
                   "metrics": data["metrics"], "meta": data["meta"], "peak_rss_mb": data.get("peak_rss_mb"),
                   "scored_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            cache[key] = rec
            append_cache(cache_path, rec)
            recs.append(rec)
        return {"recs": recs}

    results: list[dict] = []
    for row in rows:
        out_row = {k: row[k] for k in ("submitted", "task", "file", "board", "board_score")}
        out_row.update({"status": "", "note": "", "file_sha256": "", "n_seeds": 0,
                        "local_headline_mean": None, "local_headline_sd": None, "local_minus_board": None,
                        "prediction_cells": None, "raw_mean": {}, "skill_mean": {}, "weights_key": ""})
        results.append(out_row)
        if not row["file"]:
            out_row["status"] = "missing_file"
            out_row["note"] = "blank file name"
            continue
        if not row["board"]:
            out_row["status"] = "no_board"
            out_row["note"] = "board blank: set it by hand in submissions.csv"
            continue
        if row["board"] not in boards:
            out_row["status"] = "board_not_configured"
            out_row["note"] = "no entry for this board in boards.json"
            continue
        res = resolved[row["file"]]
        if res.path is None:
            out_row["status"] = "missing_file"
            out_row["note"] = res.note
            continue
        out_row["file_sha256"] = res.sha
        out_row["weights_key"] = boards[row["board"]]["weights_key"]
        pair_key = (row["file"], row["board"])
        if pair_key not in pair_cache:
            try:
                pair_cache[pair_key] = score_pair(row["file"], row["board"])
            except WorkerError as exc:
                pair_cache[pair_key] = {"error": str(exc)}
        pr = pair_cache[pair_key]
        if "error" in pr:
            out_row["status"] = "scoring_error"
            out_row["note"] = pr["error"]
            continue
        cfg = boards[row["board"]]
        heads = []
        raws = {m: [] for m in ml.BOARDS[cfg["weights_key"]]["metrics"]}
        skills: dict[str, list] = {}
        for rec in pr["recs"]:
            h = board_headline(rec["metrics"], cfg["entry"], cfg["weights_key"])
            heads.append(h["headline"])
            for m, v in h["raw"].items():
                raws[m].append(v)
            for m, v in h["skills"].items():
                skills.setdefault(m, []).append(v)
        out_row["status"] = "scored" if res.status != "ambiguous_newest" else "scored_ambiguous_name"
        out_row["note"] = res.note
        out_row["n_seeds"] = len(heads)
        out_row["local_headline_mean"] = mean_or_none(heads)
        out_row["local_headline_sd"] = sd_or_none(heads)
        if row["board_score"] is not None and out_row["local_headline_mean"] is not None:
            out_row["local_minus_board"] = out_row["local_headline_mean"] - row["board_score"]
        out_row["prediction_cells"] = pr["recs"][0]["meta"].get("prediction_cells")
        out_row["raw_mean"] = {m: mean_or_none(v) for m, v in raws.items()}
        out_row["skill_mean"] = {m: mean_or_none(v) for m, v in skills.items()}
        pc = out_row["prediction_cells"]
        entry = cfg["entry"]
        if isinstance(pc, int) and not (entry["min_cells"] <= pc <= entry["max_cells"]):
            out_row["note"] = (out_row["note"] + f"; {pc} cells outside board limits "
                               f"[{entry['min_cells']}, {entry['max_cells']}] (scored anyway)").lstrip("; ")

    if not args.keep_work:
        shutil.rmtree(work_root, ignore_errors=True)

    used_boards = [b for b in boards if any(r["board"] == b for r in results)]
    write_outputs(out, args, results, boards, used_boards, validator, index_source, index_sha,
                  scorer_sig, vk_version, worker_calls)
    n_scored = sum(1 for r in results if r["status"].startswith("scored"))
    print(f"rows {len(results)}; scored {n_scored}; worker calls this run {worker_calls}; "
          f"outputs in {out}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------------------------------

def _rho(x, nd=3) -> str:
    """Spearman values: 'n/a' when undefined (fewer than 3 pairs, or one side constant)."""
    return "n/a" if x is None else f"{x:.{nd}f}"


def _fmt(x, nd=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return ""
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def write_outputs(out, args, results, boards, used_boards, validator, index_source, index_sha,
                  scorer_sig, vk_version, worker_calls) -> None:
    metric_names = _metric_order([boards[b]["weights_key"] for b in used_boards]) if used_boards else []
    base_cols = ["submitted", "task", "file", "board", "board_score", "status", "note", "file_sha256",
                 "n_seeds", "local_headline_mean", "local_headline_sd", "local_minus_board", "prediction_cells"]
    metric_cols = [f"raw_{m}_mean" for m in metric_names] + [f"skill_{m}_mean" for m in metric_names]
    with open(out / "rescore.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(base_cols + metric_cols)
        for r in results:
            vals = [_fmt(r.get(c), 4) if isinstance(r.get(c), float) else ("" if r.get(c) is None else r.get(c))
                    for c in base_cols]
            for m in metric_names:
                vals.append(_fmt(r["raw_mean"].get(m), 6) if r["raw_mean"] else "")
            for m in metric_names:
                vals.append(_fmt(r["skill_mean"].get(m), 4) if r["skill_mean"] else "")
            w.writerow(vals)

    write_report(out, args, results, boards, used_boards, validator, index_source, index_sha,
                 scorer_sig, vk_version)


def write_report(out, args, results, boards, used_boards, validator, index_source, index_sha,
                 scorer_sig, vk_version) -> None:
    L: list[str] = []
    synthetic = [b for b in used_boards if boards[b]["synthetic"]]
    L.append("# Local rescoring of a submission history")
    L.append("")
    if synthetic:
        L.append(f"> SYNTHETIC DEMO: board scores for {', '.join(synthetic)} are not real board values.")
        L.append("")
    L.append(f"Generated {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} UTC.")
    L.append("")
    L.append(f"- Protocol: `{args.protocol}`. Seeds: {args.seeds} (0 to {args.seeds - 1}).")
    fractions = sorted({boards[b]['fraction'] for b in used_boards})
    if args.protocol == "board":
        L.append(f"- Stage subsample rate: {', '.join(f'{f:g}' for f in fractions)} (board protocol); "
                 "scored against half A of the target.")
    else:
        L.append("- Scored against the whole released target and reference (no subsample).")
    L.append(f"- Panel index: `{index_source}` (sha256 {index_sha[:12]}).")
    L.append(f"- Scorer: veckit {vk_version} (source sha256 {scorer_sig[:12]}).")
    L.append("- Board weights and directions: metric-lens `BOARDS`. Anchors: the panel index.")
    L.append("")
    L.append("A local rescoring is an analysis of files you already submitted. It is not a score, and it "
             "cannot show the hidden test result.")
    L.append("")

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"] or "unknown"] = counts.get(r["status"] or "unknown", 0) + 1
    L.append("## Coverage")
    L.append("")
    L.append(f"- Rows in submissions.csv: {len(results)}")
    for s in sorted(counts):
        L.append(f"- {s}: {counts[s]}")
    problem_rows = [r for r in results if r["status"] != "scored" or "board limits" in r["note"]]
    if problem_rows:
        L.append("")
        L.append("| file | board | status | note |")
        L.append("|---|---|---|---|")
        for r in problem_rows:
            L.append(f"| {r['file']} | {r['board'] or '(blank)'} | {r['status']} | {r['note']} |")
    if WARNINGS:
        L.append("")
        L.append("Warnings from this run:")
        for wmsg in WARNINGS:
            L.append(f"- {wmsg}")
    L.append("")

    for board in used_boards:
        cfg = boards[board]
        rs = [r for r in results if r["board"] == board and r["status"].startswith("scored")]
        cmp_rows = [r for r in rs if r["board_score"] is not None and r["local_headline_mean"] is not None]
        L.append(f"## {board}")
        L.append("")
        L.append(f"- Files scored: {len(rs)}; with a board score: {len(cmp_rows)}")
        if cmp_rows:
            diffs = [r["local_minus_board"] for r in cmp_rows]
            m, s = mean_or_none(diffs), sd_or_none(diffs)
            L.append(f"- Local minus board: mean {_fmt(m)}, sd {_fmt(s)} (n={len(diffs)})")
            seed_sds = [r["local_headline_sd"] for r in cmp_rows if r["local_headline_sd"] is not None]
            if seed_sds:
                L.append(f"- Seed sd of the local headline, mean over files: {_fmt(mean_or_none(seed_sds))} "
                         f"(n={len(seed_sds)} files)")
            rho, n = spearman([r["local_headline_mean"] for r in cmp_rows], [r["board_score"] for r in cmp_rows])
            L.append(f"- Spearman rho, local vs board headline: {_rho(rho)} (n={n})")
            L.append("")
            L.append("Largest disagreements (local minus board):")
            L.append("")
            L.append("| file | submitted | board | board score | local mean | difference |")
            L.append("|---|---|---|---:|---:|---:|")
            for r in sorted(cmp_rows, key=lambda r: abs(r["local_minus_board"]), reverse=True)[:5]:
                L.append(f"| {r['file']} | {r['submitted']} | {board} | {_fmt(r['board_score'])} | "
                         f"{_fmt(r['local_headline_mean'])} | {_fmt(r['local_minus_board'])} |")
            L.append("")
            L.append("Which metric moved the board: Spearman rho of each metric's local skill against the board "
                     "score. n/a means the metric did not vary across these files (or fewer than 3 files).")
            L.append("")
            L.append("| metric | rho | n |")
            L.append("|---|---:|---:|")
            for m in ml.BOARDS[cfg["weights_key"]]["metrics"]:
                rho_m, n_m = spearman([r["skill_mean"].get(m) for r in cmp_rows],
                                      [r["board_score"] for r in cmp_rows])
                L.append(f"| {m} | {_rho(rho_m)} | {n_m} |")
            if validator:
                pairs = [(validator.get((r["file"], board)), r) for r in cmp_rows]
                pairs = [(v, r) for v, r in pairs if v is not None]
                if pairs:
                    vals = [v for v, _ in pairs]
                    rho_b, n_b = spearman(vals, [r["board_score"] for _, r in pairs])
                    rho_l, n_l = spearman(vals, [r["local_headline_mean"] for _, r in pairs])
                    L.append("")
                    L.append(f"Local validator column: Spearman vs board {_rho(rho_b)} (n={n_b}); "
                             f"vs local headline {_rho(rho_l)} (n={n_l}).")
        L.append("")
    (out / "RESCORE.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--_worker":
        worker_main(sys.argv[2])
        sys.exit(0)
    sys.exit(main())
