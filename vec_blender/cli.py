from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io import read_h5ad, summarize
from .methods import mean_graft, population_mix, quantile_graft, spatial_transplant


METHODS = ("mixture", "mean-graft", "quantile-graft", "spatial-transplant")


def _manifest_path(out: Path) -> Path:
    return out.with_suffix(out.suffix + ".blend.json")


def _write_result(result, out: Path, a_path: Path, b_path: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    result.adata.write_h5ad(out)
    manifest = {
        **result.report,
        "input_a": str(a_path),
        "input_b": str(b_path),
        "output": str(out),
        "cells": int(result.adata.n_obs),
        "genes": int(result.adata.n_vars),
    }
    _manifest_path(out).write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def _run_blend(args) -> None:
    a_path, b_path = Path(args.a), Path(args.b)
    a, b = read_h5ad(a_path), read_h5ad(b_path)

    if args.method == "mixture":
        result = population_mix(a, b, alpha=args.alpha, n_out=args.n_out, seed=args.seed)
    elif args.method == "mean-graft":
        result = mean_graft(a, b, clip_min=args.clip_min)
    elif args.method == "quantile-graft":
        result = quantile_graft(a, b)
    elif args.method == "spatial-transplant":
        result = spatial_transplant(
            a,
            b,
            n_out=args.n_out,
            seed=args.seed,
            n_components=args.components,
            assignment=args.assignment,
            exact_limit=args.exact_limit,
        )
    else:
        raise AssertionError(args.method)

    _write_result(result, Path(args.output), a_path, b_path)


def _run_sweep(args) -> None:
    a_path, b_path = Path(args.a), Path(args.b)
    a, b = read_h5ad(a_path), read_h5ad(b_path)
    alphas = [float(x) for x in args.alphas.split(",") if x.strip()]
    if not alphas:
        raise ValueError("--alphas must contain at least one value")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for alpha in alphas:
        result = population_mix(a, b, alpha=alpha, n_out=args.n_out, seed=args.seed)
        tag = f"{alpha:.4f}".rstrip("0").rstrip(".").replace(".", "p")
        out = out_dir / f"mix_alpha_{tag}.h5ad"
        _write_result(result, out, a_path, b_path)
        index.append({"alpha": alpha, "path": str(out)})
    (out_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")


def _run_inspect(args) -> None:
    rows = []
    for p in args.files:
        adata = read_h5ad(p)
        rows.append(summarize(p, adata))
    print(json.dumps(rows, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vec-blend",
        description="Compose two Virtual Embryo .h5ad predictions without score feedback.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    blend = sub.add_parser("blend", help="produce one blended submission")
    blend.add_argument("a", help="submission A")
    blend.add_argument("b", help="submission B")
    blend.add_argument("-o", "--output", required=True)
    blend.add_argument("--method", choices=METHODS, required=True)
    blend.add_argument("--alpha", type=float, default=0.5, help="A fraction for mixture")
    blend.add_argument("--n-out", type=int, default=None)
    blend.add_argument("--seed", type=int, default=0)
    blend.add_argument("--clip-min", type=float, default=None)
    blend.add_argument("--components", type=int, default=24)
    blend.add_argument(
        "--assignment", choices=("auto", "hungarian", "greedy"), default="auto"
    )
    blend.add_argument("--exact-limit", type=int, default=2500)
    blend.set_defaults(func=_run_blend)

    sweep = sub.add_parser("sweep", help="generate a fixed mixture-alpha family")
    sweep.add_argument("a")
    sweep.add_argument("b")
    sweep.add_argument("--out-dir", required=True)
    sweep.add_argument(
        "--alphas", default="0,0.25,0.5,0.75,1", help="comma-separated values"
    )
    sweep.add_argument("--n-out", type=int, default=None)
    sweep.add_argument("--seed", type=int, default=0)
    sweep.set_defaults(func=_run_sweep)

    inspect = sub.add_parser("inspect", help="summarize one or more submissions")
    inspect.add_argument("files", nargs="+")
    inspect.set_defaults(func=_run_inspect)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
