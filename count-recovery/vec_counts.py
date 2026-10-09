#!/usr/bin/env python3
"""Recover integer counts from CP10k-normalized, natural-log1p AnnData matrices.

Each stored value is x = log(1 + 1e4 * c / L), where c is an integer count and L is
the cell's library size, the sum of its counts over all genes. Recovery inverts this
map and checks that every value lands on an integer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import sys
import time
from datetime import date
from pathlib import Path
from typing import NamedTuple

import anndata as ad
import h5py
import numpy as np
from scipy import sparse

VERSION = "1.1.0"
CP_TARGET = 10_000.0
FLOAT32_EPS = float(np.finfo(np.float32).eps)
# A value s passes when |s - round(s)| <= tol * max(1, s). Float32 storage of the log1p
# values moves s by a few times 1e-7 relative; the worst normalized residual on the
# E8.5 stand-in was 3.3e-7. The default is 16 float32 epsilons (about 1.9e-6).
DEFAULT_TOL = 16 * FLOAT32_EPS
# Relative tolerance for sum(counts) against the inferred library size. Float32 error in
# the smallest value is far below this, while a normalization total that differs from
# the sum over the stored genes (for example log1p(CPM)) is far above it.
CP_SUM_RTOL = 1e-5
MAX_SMALLEST_COUNT = 5
# Above this slack, rounding cannot tell integers apart, so no cell may need it.
MAX_SLACK = 0.5
OUTPUT_OBS_COLUMNS = ("library_size", "recovery_max_residual", "recovery_smallest_count")


class _Recovery(NamedTuple):
    counts: sparse.csr_matrix
    library: np.ndarray
    residual: np.ndarray
    smallest: np.ndarray
    library_error: np.ndarray
    all_zero: np.ndarray
    failing: np.ndarray
    explicit_zeros: int


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def peak_rss_mb() -> float:
    # macOS reports bytes; Linux reports KiB.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return float(value / (1024 * 1024 if sys.platform == "darwin" else 1024))


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _load_x(path: str | Path):
    """Load only X from its HDF5 encoding. Dense X is returned as a numpy array."""
    with h5py.File(path, "r") as h5:
        if "X" not in h5:
            raise ValueError(f"{Path(path).name} has no X matrix")
        node = h5["X"]
        if isinstance(node, h5py.Dataset):
            return np.asarray(node[...])
        encoding = _text(node.attrs.get("encoding-type", ""))
        if encoding:
            kind = encoding.lower()
            if "csc" in kind:
                fmt = "csc"
            elif "csr" in kind:
                fmt = "csr"
            else:
                raise ValueError(f"Unsupported sparse X encoding: {encoding!r}")
            shape_attr = node.attrs.get("shape")
        else:
            # AnnData before 0.7 stored the format in h5sparse_format and the shape in
            # h5sparse_shape. Newer readers still accept these files.
            fmt = _text(node.attrs.get("h5sparse_format", ""))
            if fmt not in ("csr", "csc"):
                raise ValueError(
                    "X is a group with no encoding-type attribute and is not a legacy "
                    "sparse matrix; re-save the file with anndata 0.8 or newer"
                )
            shape_attr = node.attrs.get("h5sparse_shape")
        if shape_attr is None:
            raise ValueError("sparse X has no shape attribute")
        shape = tuple(int(v) for v in shape_attr)
        data = node["data"][...]
        indices = node["indices"][...]
        indptr = node["indptr"][...]
    cls = sparse.csc_matrix if fmt == "csc" else sparse.csr_matrix
    return cls((data, indices, indptr), shape=shape)


def _as_csr(matrix):
    """Return a CSR view or conversion of X without modifying the input."""
    if sparse.issparse(matrix):
        return matrix.tocsr()
    return sparse.csr_matrix(np.asarray(matrix))


def _check_values(csr) -> None:
    data = csr.data
    if data.size == 0:
        return
    bad = ~np.isfinite(data)
    if bad.any():
        first = int(np.flatnonzero(bad)[0])
        cell = int(np.searchsorted(csr.indptr, first, side="right") - 1)
        raise ValueError(
            f"X has {int(bad.sum())} non-finite values (NaN or Inf); first one is in cell {cell}"
        )
    if float(data.min()) < 0:
        raise ValueError("X has negative values; expected natural log1p of non-negative counts")


def _recover_rows(csr, tol: float) -> _Recovery:
    """Recover integer counts cell by cell. The input matrix is only read."""
    n_cells, n_genes = csr.shape
    indptr, indices, data = csr.indptr, csr.indices, csr.data
    nnz = data.size
    out_data = np.empty(nnz, dtype=np.int32)
    out_indices = np.empty(nnz, dtype=np.int32)
    out_indptr = np.zeros(n_cells + 1, dtype=np.int32)
    library = np.zeros(n_cells)
    residual = np.zeros(n_cells)
    smallest = np.zeros(n_cells, dtype=np.int16)
    library_error = np.zeros(n_cells)
    all_zero = np.zeros(n_cells, dtype=bool)
    failing: list[int] = []
    explicit_zeros = int(np.count_nonzero(data == 0))
    pos = 0
    for cell in range(n_cells):
        start, end = int(indptr[cell]), int(indptr[cell + 1])
        raw = data[start:end]
        present = raw != 0
        if not present.any():
            all_zero[cell] = True
            out_indptr[cell + 1] = pos
            continue
        vals = np.expm1(raw[present].astype(np.float64))
        cols = indices[start:end][present]
        vmin = float(vals.min())
        chosen = None
        best = np.inf
        for k in range(1, MAX_SMALLEST_COUNT + 1):
            # Assume the cell's least-expressed detected gene has count k.
            scaled = vals * (k / vmin)
            rounded = np.rint(scaled)
            rel = float(np.max(np.abs(scaled - rounded) / np.maximum(1.0, scaled)))
            best = min(best, rel)
            if rel <= tol and tol * max(1.0, float(scaled.max())) < MAX_SLACK:
                chosen = (k, rounded, rel)
                break
        if chosen is None:
            failing.append(cell)
            residual[cell] = best
            out_indptr[cell + 1] = pos
            continue
        k, rounded, rel = chosen
        n = rounded.size
        out_data[pos:pos + n] = rounded.astype(np.int32)
        out_indices[pos:pos + n] = cols
        pos += n
        out_indptr[cell + 1] = pos
        lib = k * CP_TARGET / vmin
        library[cell] = lib
        residual[cell] = rel
        smallest[cell] = k
        library_error[cell] = abs(float(rounded.sum()) - lib)
    counts = sparse.csr_matrix((out_data[:pos], out_indices[:pos], out_indptr),
                               shape=(n_cells, n_genes))
    return _Recovery(counts, library, residual, smallest, library_error, all_zero,
                     np.asarray(failing, dtype=np.int64), explicit_zeros)


def _metadata(path: str | Path):
    try:
        data = ad.read_h5ad(path, backed="r")
    except Exception as exc:  # anndata raises several unrelated types for unreadable files
        raise ValueError(f"could not read AnnData metadata from {Path(path).name}: {exc}") from exc
    try:
        return data.obs.copy(), data.var.copy()
    finally:
        data.file.close()


def _names(path: str | Path):
    data = ad.read_h5ad(path, backed="r")
    try:
        return data.obs_names.to_numpy(), data.var_names.to_numpy()
    finally:
        data.file.close()


def _validate_tol(tol: float) -> None:
    if not (0.0 < tol < 0.5):
        raise ValueError(f"tol must satisfy 0 < tol < 0.5, got {tol}")


def _make_report(input_path: Path, input_hash: str, rec: _Recovery, tol: float) -> dict:
    n = int(rec.library.size)
    ok = np.ones(n, dtype=bool)
    ok[rec.failing] = False
    lib_rel = np.divide(rec.library_error, rec.library, out=np.zeros(n), where=rec.library > 0)
    if ok.any():
        quantiles = np.quantile(rec.library[ok], [0, .25, .5, .75, 1]).tolist()
    else:
        quantiles = [0.0] * 5
    return {
        "tool_version": VERSION,
        "input_filename": input_path.name,
        "input_sha256": input_hash,
        "tolerance": float(tol),
        "n_cells": n,
        "n_genes": int(rec.counts.shape[1]),
        "fraction_residual_below_tol": float(np.mean(ok)) if n else 1.0,
        "worst_residual": float(rec.residual.max()) if n else 0.0,
        "library_size_quantiles_min_p25_median_p75_max": quantiles,
        "cells_needing_smallest_count_gt_1": int(np.count_nonzero(rec.smallest > 1)),
        "smallest_count_histogram": {
            str(k): int(np.count_nonzero(rec.smallest == k)) for k in range(1, MAX_SMALLEST_COUNT + 1)
        },
        "all_zero_cells": np.flatnonzero(rec.all_zero).astype(int).tolist(),
        "explicit_zeros_dropped": int(rec.explicit_zeros),
        "failing_cell_indices": rec.failing.astype(int).tolist(),
        "cp10k_check": {
            "rel_tolerance": CP_SUM_RTOL,
            "max_abs_sum_minus_library": float(rec.library_error.max()) if n else 0.0,
            "max_rel_sum_minus_library": float(lib_rel.max()) if n else 0.0,
            "failing_cell_indices": np.flatnonzero(lib_rel > CP_SUM_RTOL).astype(int).tolist(),
        },
        "recovered_nonzero_count": int(rec.counts.nnz),
    }


def _print_report(report: dict) -> None:
    q = report["library_size_quantiles_min_p25_median_p75_max"]
    cp = report["cp10k_check"]
    print("| Metric | Result |\n|---|---:|")
    print(f"| Cells | {report['n_cells']} |")
    print(f"| Cells passing integer check | {report['n_cells'] - len(report['failing_cell_indices'])} |")
    print(f"| Worst normalized residual | {report['worst_residual']:.3g} |")
    print(f"| Library size min / p25 / median / p75 / max | {', '.join(f'{v:.6g}' for v in q)} |")
    print(f"| Cells needing assumed smallest count > 1 | {report['cells_needing_smallest_count_gt_1']} |")
    print(f"| Max abs(sum(counts) - library size) | {cp['max_abs_sum_minus_library']:.4g} |")
    print(f"| Max relative deviation of sum(counts) | {cp['max_rel_sum_minus_library']:.3g} |")
    print(f"| All-zero cells | {len(report['all_zero_cells'])} |")
    print(f"| Explicit zeros dropped | {report['explicit_zeros_dropped']} |")
    print(f"| Failing cells | {len(report['failing_cell_indices'])} |")
    print(f"| Peak RSS (MB) | {report['peak_rss_mb']:.1f} |")
    print(f"| Runtime (s) | {report['runtime_seconds']:.2f} |")


def _emit(report: dict, report_path: Path | None, started: float) -> None:
    report["runtime_seconds"] = time.perf_counter() - started
    report["peak_rss_mb"] = peak_rss_mb()
    _print_report(report)
    if report_path is not None:
        report_path.write_text(json.dumps(report, indent=2) + "\n")


def recover(input_path: str | Path, output_path: str | Path | None = None, check_only: bool = False,
            tol: float = DEFAULT_TOL, keep_log1p: bool = False, force: bool = False,
            report_path: str | Path | None = None) -> dict:
    _validate_tol(tol)
    input_path = Path(input_path)
    if check_only and output_path is not None:
        raise ValueError("--check-only does not write a matrix; omit the output path (use --report for a JSON file)")
    if not check_only and output_path is None:
        raise ValueError("an output path is required unless --check-only is given")
    out = None if output_path is None else Path(output_path)
    if out is not None and out.resolve() == input_path.resolve():
        raise ValueError("the output path must differ from the input path")
    if report_path is None and out is not None:
        report_path = out.with_name(out.name + ".json")
    report_file = None if report_path is None else Path(report_path)
    if not force:
        for target in (out, report_file):
            if target is not None and target.exists():
                raise ValueError(f"{target} already exists; pass --force to overwrite it")

    started = time.perf_counter()
    input_hash = sha256(input_path)
    obs, var = _metadata(input_path)
    if not check_only:
        clash = [column for column in OUTPUT_OBS_COLUMNS if column in obs.columns]
        if clash and not force:
            raise ValueError(f"input obs already has {clash}; pass --force to overwrite them")
    matrix = _load_x(input_path)
    csr = _as_csr(matrix)
    del matrix
    _check_values(csr)
    rec = _recover_rows(csr, tol)
    report = _make_report(input_path, input_hash, rec, tol)

    if rec.failing.size:
        _emit(report, report_file, started)
        first = ", ".join(str(int(i)) for i in rec.failing[:10])
        where = f"; see {report_file}" if report_file is not None else ""
        raise ValueError(
            f"{rec.failing.size} cells failed integer recovery (no assumed smallest count from 1 to "
            f"{MAX_SMALLEST_COUNT} fits within tolerance {tol:g}); first cells: {first}{where}"
        )
    cp_fail = report["cp10k_check"]["failing_cell_indices"]
    if cp_fail:
        _emit(report, report_file, started)
        raise ValueError(
            f"{len(cp_fail)} cells fail the CP10k check: the sum of recovered counts differs from the "
            f"inferred library size by up to relative {report['cp10k_check']['max_rel_sum_minus_library']:.3g} "
            f"(limit {CP_SUM_RTOL:g}). The input may not be CP10k-normalized over all genes, for example log1p(CPM)"
        )
    if check_only:
        _emit(report, report_file, started)
        return report

    obs["library_size"] = rec.library
    obs["recovery_max_residual"] = rec.residual
    obs["recovery_smallest_count"] = rec.smallest
    result = ad.AnnData(X=rec.counts, obs=obs, var=var)
    if keep_log1p:
        result.layers["log1p"] = csr
    result.uns["vec_counts"] = {
        "tool_version": VERSION, "input_filename": input_path.name, "input_sha256": input_hash,
        "tolerance": float(tol), "cp10k_rel_tolerance": CP_SUM_RTOL, "date": date.today().isoformat(),
        "method": "CP10k log1p inverse with per-cell integer validation and CP10k sum check",
    }
    result.write_h5ad(out, compression="gzip")
    report["output_size_bytes"] = out.stat().st_size
    _emit(report, report_file, started)
    return report


def roundtrip(recovered_path: str | Path, original_path: str | Path, chunk_rows: int = 128) -> dict:
    """Compare CP10k/log1p recovered counts to the original X, a block of rows at a time."""
    started = time.perf_counter()
    original_csr = _as_csr(_load_x(original_path))
    original_obs, original_var = _names(original_path)
    recovered = ad.read_h5ad(recovered_path, backed="r")
    try:
        shape = recovered.shape
        if shape != original_csr.shape:
            raise ValueError(f"Shape mismatch: recovered {shape}, original {original_csr.shape}")
        if not np.array_equal(recovered.obs_names.to_numpy(), original_obs):
            raise ValueError("obs_names differ between the recovered and original files")
        if not np.array_equal(recovered.var_names.to_numpy(), original_var):
            raise ValueError("var_names differ between the recovered and original files")
        max_delta = 0.0
        for start in range(0, shape[0], chunk_rows):
            end = min(start + chunk_rows, shape[0])
            counts = recovered.X[start:end]
            counts = counts.tocsr() if sparse.issparse(counts) else sparse.csr_matrix(np.asarray(counts))
            sums = np.asarray(counts.sum(axis=1)).ravel()
            per_cell_scale = np.divide(CP_TARGET, sums, out=np.zeros_like(sums, dtype=float), where=sums != 0)
            expected = counts.multiply(per_cell_scale[:, None]).tocsr()
            expected.data = np.log1p(expected.data)
            actual = original_csr[start:end]
            delta = expected - actual
            if delta.nnz:
                max_delta = max(max_delta, float(np.max(np.abs(delta.data))))
    finally:
        recovered.file.close()
    result = {"rows": shape[0], "columns": shape[1], "max_abs_delta": max_delta,
              "runtime_seconds": time.perf_counter() - started, "peak_rss_mb": peak_rss_mb()}
    print(f"Roundtrip CP10k/log1p max|delta|: {max_delta:.8g} ({shape[0]} x {shape[1]})")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("recover", help="recover integer counts, or only check them with --check-only")
    rec.add_argument("input", help="input .h5ad with CP10k log1p values in X")
    rec.add_argument("output", nargs="?", help="output .h5ad (omit with --check-only)")
    rec.add_argument("--check-only", action="store_true", help="validate without writing a matrix")
    rec.add_argument("--report", help="JSON report path (default: OUTPUT.json)")
    rec.add_argument("--tol", type=float, default=DEFAULT_TOL,
                     help="relative integer tolerance, 0 < tol < 0.5 (default: %(default)g)")
    rec.add_argument("--keep-log1p", action="store_true", help="also keep the input as layers['log1p']")
    rec.add_argument("--force", action="store_true", help="overwrite an existing output, report or obs column")
    rt = sub.add_parser("roundtrip", help="compare recovered counts to the original log1p X")
    rt.add_argument("recovered")
    rt.add_argument("original")
    args = parser.parse_args(argv)
    try:
        if args.command == "recover":
            recover(args.input, args.output, check_only=args.check_only, tol=args.tol,
                    keep_log1p=args.keep_log1p, force=args.force, report_path=args.report)
        else:
            roundtrip(args.recovered, args.original)
    except (ValueError, OSError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
