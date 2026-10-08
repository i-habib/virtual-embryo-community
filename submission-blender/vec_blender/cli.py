from __future__ import annotations

import argparse
import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .io import read_h5ad, summarize, validate_submission_output
from .methods import mean_graft, population_mix, quantile_graft, spatial_transplant


METHODS = ("mixture", "mean-graft", "quantile-graft", "spatial-transplant")


def _manifest_path(out: Path) -> Path:
    return out.with_suffix(out.suffix + ".blend.json")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _package_version() -> str:
    try:
        return version("vec-submission-blender")
    except PackageNotFoundError:
        return "unknown"


def _write_result(result, out: Path, a_path: Path, b_path: Path) -> None:
    validate_submission_output(result.adata)
    out.parent.mkdir(parents=True, exist_ok=True)
    result.adata.write_h5ad(out)
    output_bytes = int(out.stat().st_size)
    manifest = {
        **result.report,
        "vec_blend_version": _package_version(),
        "input_a": str(a_path),
        "input_b": str(b_path),
        "input_a_sha256": _sha256(a_path),
        "input_b_sha256": _sha256(b_path),
        "output": str(out),
        "output_bytes": output_bytes,
        "output_mib": output_bytes / (1024**2),
        "cells": int(result.adata.n_obs),
        "genes": int(result.adata.n_vars),
    }
    _manifest_path(out).write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def _run_blend(args) -> None:
    a_path, b_path = Path(args.a), Path(args.b)
    a, b = read_h5ad(a_path), read_h5ad(b_path)
    if args.clip_min is not None and args.clip_min < 0:
        raise ValueError("--clip-min must be >= 0")

    if args.method == "mixture":
        result = population_mix(a, b, alpha=args.alpha, n_out=args.n_out, seed=args.seed)
    elif args.method == "mean-graft":
        result = mean_graft(a, b, clip_min=args.clip_min, chunk_rows=args.chunk_rows)
        if args.clip_min is None and result.report["negative_fraction_before_clipping"] > 0:
            pct = 100.0 * result.report["negative_fraction_before_clipping"]
            raise ValueError(
                "mean-graft produced negative expression values "
                f"({pct:.3g}% of entries). veckit rejects negative prediction.X. "
                "Re-run with --clip-min 0 to floor the result."
            )
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
            max_match_genes=args.max_match_genes,
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
    if args.n_out is None:
        if a.n_obs != b.n_obs:
            raise ValueError(
                "A and B have different cell counts. Pass --n-out so a sweep "
                "changes mixture proportion without also changing output size."
            )
        n_out = int(a.n_obs)
    else:
        n_out = int(args.n_out)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for alpha in alphas:
        result = population_mix(a, b, alpha=alpha, n_out=n_out, seed=args.seed)
        tag = f"{alpha:.4f}".rstrip("0").rstrip(".").replace(".", "p")
        out = out_dir / f"mix_alpha_{tag}.h5ad"
        _write_result(result, out, a_path, b_path)
        index.append({"alpha": alpha, "n_out": n_out, "path": str(out)})
    (out_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")


def _run_inspect(args) -> None:
    rows = []
    for p in args.files:
        rows.append(summarize(p, read_h5ad(p)))
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
    blend.add_argument(
        "--clip-min",
        type=float,
        default=None,
        help="nonnegative floor for mean-graft expression; usually 0",
    )
    blend.add_argument(
        "--chunk-rows", type=int, default=512, help="row chunk size for mean graft"
    )
    blend.add_argument("--components", type=int, default=24)
    blend.add_argument(
        "--assignment", choices=("auto", "hungarian", "greedy"), default="auto"
    )
    blend.add_argument("--exact-limit", type=int, default=2500)
    blend.add_argument(
        "--max-match-genes",
        type=int,
        default=2048,
        help="cap genes materialized for spatial matching; highest pooled variance are used",
    )
    blend.set_defaults(func=_run_blend)

    sweep = sub.add_parser("sweep", help="generate a fixed-size mixture-alpha family")
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
