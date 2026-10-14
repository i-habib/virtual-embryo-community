#!/usr/bin/env python3
"""Re-check a prediction .h5ad against one board's contract in index.json.

    python check_test_contract.py --list
    python check_test_contract.py PRED.h5ad BOARD_KEY [--index PATH] [--panels-dir DIR]

The board contract is the organisers' index.json at
https://virtualembryo.ai/challenge/panels/index.json, with each gene list at
https://virtualembryo.ai/challenge/panels/<genes_file>. The script reads any
board key that index.json contains, so boards that open with the test phase on
20 October 2026 work without a code change.

Checks: the gene list matches genes_sha256 in the index, var names match the
panel in the same order, the cell count is within min_cells and max_cells,
every obsm_required key is present with one row per cell and finite values,
and X is finite and non-negative. Listing and the gene-list hash need only the
standard library. Reading a .h5ad needs anndata, numpy and scipy.

This does not check the log1p(CP10k) scale or the file's sha256. For those,
use vec_submit_check in https://github.com/xxx12e/vec-community-kit (also
https://github.com/gh-dv-openclaw/vec-submit-check). It is kept here only to
re-check a file against boards that appear on 20 October. The organisers'
upload check and scorer have the final say.

Exit codes: 0 all checks pass, 1 at least one check fails, 2 usage or read error.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

PANELS_URL = "https://virtualembryo.ai/challenge/panels/"
INDEX_URL = PANELS_URL + "index.json"
TIMEOUT_S = 60


def _fetch(url):
    # The panels host answers 403 to urllib's default User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "check_test_contract/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read()


def load_index(path=None):
    data = Path(path).read_bytes() if path else _fetch(INDEX_URL)
    return json.loads(data.decode("utf-8"))


def load_gene_lines(board, panels_dir=None):
    name = board["genes_file"]
    raw = (Path(panels_dir) / name).read_bytes() if panels_dir else _fetch(PANELS_URL + name)
    return raw.decode("utf-8").splitlines()


def gene_hash(lines):
    """Same convention as genes_sha256 in index.json: SHA-256 of the names joined by newlines, first 16 hex digits."""
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


def _try_import():
    try:
        import anndata
        import numpy
        import scipy.sparse
    except ImportError:
        return None
    return anndata, numpy, scipy.sparse


def check_file(path, board, genes, libs):
    """Return a list of (ok, message) for one prediction file against one board."""
    ad, np, sp = libs
    results = []

    def add(ok, msg):
        results.append((bool(ok), msg))

    adata = ad.read_h5ad(path)
    n_obs, n_vars = adata.shape

    names = [str(g) for g in adata.var_names]
    if len(names) != len(genes):
        add(False, f"gene count {len(names)}, panel has {len(genes)}")
    else:
        diff = [i for i, (a, b) in enumerate(zip(names, genes)) if a != b]
        if diff:
            i = diff[0]
            add(False, f"gene names or order differ at {len(diff)} positions; "
                       f"first at {i}: got {names[i]!r}, expected {genes[i]!r}")
        else:
            add(True, f"gene panel: {len(genes)} genes, same names and order")

    lo, hi = board.get("min_cells"), board.get("max_cells")
    add((lo is None or n_obs >= lo) and (hi is None or n_obs <= hi),
        f"cells {n_obs}, allowed [{lo}, {hi}]")

    for col in board.get("obs_required") or []:
        add(col in adata.obs.columns, f"obs[{col!r}] present")

    for key in board.get("obsm_required") or []:
        if key not in adata.obsm:
            add(False, f"obsm[{key!r}] missing")
            continue
        arr = np.asarray(adata.obsm[key], dtype=float)
        if arr.ndim != 2 or arr.shape[0] != n_obs:
            add(False, f"obsm[{key!r}] shape {arr.shape}, expected {n_obs} rows")
            continue
        add(True, f"obsm[{key!r}] has {n_obs} rows")
        if key == "spatial_3D":
            add(arr.shape[1] >= 3, f"obsm['spatial_3D'] columns: {arr.shape[1]} (at least 3 needed)")
        add(bool(np.isfinite(arr).all()), f"obsm[{key!r}] finite")

    X = adata.X
    if X is None:
        add(False, "X missing")
    else:
        vals = np.asarray(X.data if sp.issparse(X) else X, dtype=float)
        add(bool(np.isfinite(vals).all()) if vals.size else True, "X finite")
        add(bool((vals >= 0).all()) if vals.size else True, "X non-negative")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a prediction .h5ad against a board in index.json.")
    ap.add_argument("prediction", nargs="?", help="prediction .h5ad file")
    ap.add_argument("board", nargs="?", help="board key, for example T1:val")
    ap.add_argument("--index", help="local index.json instead of the one on the website")
    ap.add_argument("--panels-dir", help="directory of gene lists instead of the website")
    ap.add_argument("--list", action="store_true", help="print the board keys in index.json and exit")
    args = ap.parse_args(argv)

    try:
        index = load_index(args.index)
    except Exception as exc:
        print(f"could not read index: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for key, b in index.items():
            print(f"{key}  task={b.get('task')} split={b.get('split')} genes={b.get('n_genes')} "
                  f"cells=[{b.get('min_cells')}, {b.get('max_cells')}] obsm={b.get('obsm_required') or []}")
        return 0

    if not args.prediction or not args.board:
        ap.error("give PREDICTION and BOARD, or use --list")

    board = index.get(args.board)
    if board is None:
        print(f"board {args.board!r} is not in the index. Keys: {', '.join(index)}", file=sys.stderr)
        return 2

    try:
        genes = load_gene_lines(board, args.panels_dir)
    except Exception as exc:
        print(f"could not read gene list {board.get('genes_file')}: {exc}", file=sys.stderr)
        return 2

    results = []
    expected_hash = board.get("genes_sha256")
    if expected_hash:
        got = gene_hash(genes)
        results.append((got == expected_hash, f"gene list matches genes_sha256 in index ({got})"))

    libs = _try_import()
    if libs is None:
        print("reading .h5ad needs anndata, numpy and scipy: pip install anndata numpy scipy", file=sys.stderr)
        return 2
    try:
        results += check_file(args.prediction, board, genes, libs)
    except Exception as exc:
        print(f"could not read {args.prediction}: {exc}", file=sys.stderr)
        return 2

    for ok, msg in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    failed = [m for ok, m in results if not ok]
    if failed:
        print(f"FAIL: {len(failed)} check(s) failed for {args.board}")
        return 1
    print(f"PASS: all contract checks pass for {args.board}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
