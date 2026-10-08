#!/usr/bin/env python3
"""Map mouse gene names onto a panel and normalise raw counts over that panel.

Each input column is resolved to at most one panel symbol (exact symbol, case-only
current symbol, mouse Ensembl gene ID, or MGI synonym). Columns that resolve to the
same panel gene are summed as raw counts. Each cell is then divided by its total over
the panel genes, scaled to 10,000, and passed through natural log1p.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

VERSION = "2.0.0"
MGI_URLS = {
    "MRK_List2.rpt": "https://www.informatics.jax.org/downloads/reports/MRK_List2.rpt",
    "MRK_ENSEMBL.rpt": "https://www.informatics.jax.org/downloads/reports/MRK_ENSEMBL.rpt",
}
MGI_TIMEOUT_SECONDS = 60
# MGI marker types that can be targets. Current symbols of every other type are
# protected: they never become synonyms of a gene.
GENE_MARKER_TYPES = ("Gene", "Pseudogene")
MATCH_CLASSES = ("exact", "rescued", "conflict", "ambiguous", "unmatched")
BLOCK_ROWS = 2000
# Log-transformed CP10k values are below this bound, and their expm1 row sums are
# constant (10,000 up to float error). Raw non-integer counts fail one of the two tests.
LOG_MAX_VALUE = 20.0
LOG_SPREAD_TOLERANCE = 1e-3


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_panel(path: str | Path) -> list[str]:
    genes = [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]
    if not genes:
        raise ValueError(f"Panel is empty: {path}")
    if len(genes) != len(set(genes)):
        raise ValueError(f"Panel contains duplicate symbols: {path}")
    return genes


# ---------------------------------------------------------------------------
# MGI reference tables
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "vec-normalise" / "mgi"


def _download(url: str, target: Path, timeout: float = MGI_TIMEOUT_SECONDS) -> None:
    """Fetch url into target. The bytes go to a .part file that is renamed only when complete."""
    import urllib.request

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, open(partial, "wb") as out:
            shutil.copyfileobj(response, out, 1024 * 1024)
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _file_facts(path: Path) -> dict[str, str]:
    """Checksum plus the MGI header line and an ISO date, when the file carries them."""
    with open(path, "r", encoding="utf-8", errors="replace") as stream:
        head = [stream.readline() for _ in range(3)]
    header = head[0].rstrip("\n")
    date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", "".join(head))
    return {
        "sha256": sha256(path),
        "header": header if header.startswith("MGI Accession ID") else "",
        "file_date": date_match.group(0) if date_match else "",
    }


def _ensure_cache(cache: Path) -> None:
    """Download any missing MGI report. The download date is written once, at download time."""
    cache.mkdir(parents=True, exist_ok=True)
    for name, url in MGI_URLS.items():
        target = cache / name
        if target.exists():
            continue
        _download(url, target)
        metadata = {"url": url, "downloaded": date.today().isoformat(), **_file_facts(target)}
        meta_path = cache / f"{name}.metadata.json"
        partial = meta_path.with_name(meta_path.name + ".part")
        partial.write_text(json.dumps(metadata, indent=2) + "\n")
        os.replace(partial, meta_path)


def _mgi_root(mgi_dir: str | Path | None) -> Path:
    if mgi_dir is None:
        root = _cache_dir()
        _ensure_cache(root)
    else:
        root = Path(mgi_dir)
    missing = [name for name in MGI_URLS if not (root / name).exists()]
    if missing:
        raise FileNotFoundError(f"MGI directory must contain {', '.join(missing)}")
    return root


def _mgi_provenance(root: Path) -> dict[str, dict[str, str]]:
    provenance = {}
    for name, url in MGI_URLS.items():
        meta_path = root / f"{name}.metadata.json"
        recorded = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        provenance[name] = {
            "url": recorded.get("url", url),
            "downloaded": recorded.get("downloaded", ""),
            **_file_facts(root / name),
        }
    return provenance


@dataclass(frozen=True)
class Markers:
    gene_case: dict[str, frozenset[str]]  # casefolded current gene symbol -> gene symbols
    other_case: frozenset[str]            # casefolded current symbols of non-gene markers
    synonyms: dict[str, frozenset[str]]   # casefolded synonym -> gene symbols
    ensembl: dict[str, frozenset[str]]    # upper-case ENSMUSG ID -> current gene symbols


def _index_sets(keys: pd.Series, values: pd.Series) -> dict[str, frozenset[str]]:
    pairs = pd.DataFrame({"key": keys.to_numpy(), "value": values.to_numpy()}).drop_duplicates()
    return {key: frozenset(group) for key, group in pairs.groupby("key", sort=False)["value"]}


def _load_markers(root: Path) -> Markers:
    list_path, ens_path = root / "MRK_List2.rpt", root / "MRK_ENSEMBL.rpt"
    required = ["MGI Accession ID", "Marker Symbol", "Marker Type", "Marker Synonyms (pipe-separated)"]
    header = pd.read_csv(list_path, sep="\t", dtype=str, nrows=0).columns
    if not set(required).issubset(header):
        raise ValueError(f"{list_path.name} missing columns: {sorted(set(required) - set(header))}")
    markers = pd.read_csv(list_path, sep="\t", dtype=str, keep_default_na=False, usecols=required)
    markers = markers[markers["Marker Symbol"].ne("")]
    is_gene = markers["Marker Type"].isin(GENE_MARKER_TYPES)
    genes, others = markers[is_gene], markers[~is_gene]

    gene_symbols = genes["Marker Symbol"]
    gene_case = _index_sets(gene_symbols.str.casefold(), gene_symbols)
    other_case = frozenset(others["Marker Symbol"].str.casefold())

    synonym_rows = genes.assign(synonym=genes["Marker Synonyms (pipe-separated)"].str.split("|")).explode("synonym")
    synonym_rows = synonym_rows.assign(synonym=synonym_rows["synonym"].str.strip())
    synonym_rows = synonym_rows[synonym_rows["synonym"].ne("")]
    synonyms = _index_sets(synonym_rows["synonym"].str.casefold(), synonym_rows["Marker Symbol"])

    # MRK_ENSEMBL.rpt has no header: column 1 is the MGI accession and column 6 the
    # mouse Ensembl gene ID. The join goes through the MGI accession, not the symbol.
    ens = pd.read_csv(ens_path, sep="\t", dtype=str, keep_default_na=False, header=None,
                      usecols=[0, 5], names=["MGI Accession ID", "Ensembl Gene ID"])
    symbol_by_mgi = pd.Series(gene_symbols.to_numpy(), index=genes["MGI Accession ID"].to_numpy())
    symbol_by_mgi = symbol_by_mgi[~symbol_by_mgi.index.duplicated()]
    ens = ens.assign(ensembl=ens["Ensembl Gene ID"].str.split(".").str[0].str.upper(),
                     symbol=ens["MGI Accession ID"].map(symbol_by_mgi))
    ens = ens[ens["ensembl"].ne("") & ens["symbol"].notna()]
    ensembl = _index_sets(ens["ensembl"], ens["symbol"])
    return Markers(gene_case, other_case, synonyms, ensembl)


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------

def _rescued(target: str, method: str, present_exact: set[str]) -> tuple[str, str, str]:
    """Accept a rescue only if no exact input column already carries the target gene."""
    if target in present_exact:
        return "", "conflict", f"refused: {target} is matched by an exact input column"
    return target, "rescued", method


def _resolve_one(name: str, panel_set: set[str], present_exact: set[str], markers: Markers) -> tuple[str, str, str]:
    """Return (target, class, method) for one input column name."""
    if name in panel_set:
        return name, "exact", "exact symbol"

    key = name.casefold()
    if key in markers.gene_case or key in markers.other_case:
        current = markers.gene_case.get(key, frozenset())
        if len(current) == 1 and key not in markers.other_case:
            (target,) = current
            if target in panel_set:
                return _rescued(target, "case-insensitive current symbol", present_exact)
            return "", "unmatched", "current symbol outside panel"
        if current & panel_set:
            return "", "ambiguous", "case-only match with several current symbols"
        return "", "unmatched", "current symbol outside panel or of a non-gene marker"

    ens_key = name.split(".")[0].upper()
    if ens_key.startswith("ENSMUSG"):
        current = markers.ensembl.get(ens_key, frozenset())
        if len(current) == 1:
            (target,) = current
            if target in panel_set:
                return _rescued(target, "Ensembl ID", present_exact)
        elif current & panel_set:
            return "", "ambiguous", "Ensembl ID maps to several current symbols"
        return "", "unmatched", "Ensembl ID not listed by MGI, or outside panel"

    targets = markers.synonyms.get(key, frozenset())
    if len(targets) == 1:
        (target,) = targets
        if target in panel_set:
            return _rescued(target, "MGI synonym", present_exact)
        return "", "unmatched", "MGI synonym of a gene outside panel"
    if targets & panel_set:
        return "", "ambiguous", "synonym has several current targets"
    return "", "unmatched", "no MGI match"


def resolve_names(input_names: list[str], panel: list[str], mgi_dir: str | Path | None = None):
    """Map each input name to a panel symbol. Returns per-input rows and panel genes with no input."""
    markers = _load_markers(_mgi_root(mgi_dir))
    panel_set = set(panel)
    present_exact = set(input_names) & panel_set
    rows = []
    for name in input_names:
        target, klass, method = _resolve_one(name, panel_set, present_exact, markers)
        rows.append({"input": name, "target": target, "class": klass, "method": method})
    mapped = {row["target"] for row in rows if row["target"]}
    return rows, [gene for gene in panel if gene not in mapped]


def _counts(rows: list[dict[str, str]]) -> dict[str, int]:
    tally = Counter(row["class"] for row in rows)
    return {key: tally.get(key, 0) for key in MATCH_CLASSES}


def _mapping_frame(rows: list[dict[str, str]], missing: list[str]) -> pd.DataFrame:
    report = list(rows) + [
        {"input": "", "target": gene, "class": "missing", "method": "no input column mapped"} for gene in missing
    ]
    return pd.DataFrame(report, columns=["input", "target", "class", "method"])


def _write_mapping(path: str | Path | None, rows: list[dict[str, str]], missing: list[str]) -> None:
    if path is not None:
        _mapping_frame(rows, missing).to_csv(path, sep="\t", index=False)


# ---------------------------------------------------------------------------
# Matrix checks and panel normalisation
# ---------------------------------------------------------------------------

def _matrix(adata: ad.AnnData, layer: str | None):
    if layer:
        if layer not in adata.layers:
            raise ValueError(f"Requested layer {layer!r} not found; available layers: {list(adata.layers.keys())}")
        return adata.layers[layer]
    return adata.X


def _value_summary(matrix) -> tuple[bool, float, float, float]:
    """Return (all values are non-negative integers, min, max, fraction of non-integer stored values)."""
    if sparse.issparse(matrix):
        values = matrix.data
        implicit_zero = values.size < matrix.shape[0] * matrix.shape[1]
    else:
        values = np.asarray(matrix).ravel()
        implicit_zero = False
    if values.size == 0:
        return True, 0.0, 0.0, 0.0
    minimum, maximum = float(values.min()), float(values.max())
    if implicit_zero:
        minimum, maximum = min(minimum, 0.0), max(maximum, 0.0)
    if np.issubdtype(values.dtype, np.integer):
        fraction = 0.0  # avoids np.rint, which would upcast integer input to float64
    else:
        fraction = float(np.mean(np.abs(values - np.rint(values)) > 1e-6))
    return minimum >= 0 and fraction == 0.0, minimum, maximum, fraction


def _looks_log_cp10k(matrix) -> bool:
    """True when all values are below LOG_MAX_VALUE and each row's expm1 sum is the same total."""
    if sparse.issparse(matrix):
        csr = sparse.csr_matrix(matrix)
        values = csr.data.astype(np.float64)
        largest = float(values.max()) if values.size else 0.0
        if largest >= LOG_MAX_VALUE:
            return False
        expm1 = sparse.csr_matrix((np.expm1(values), csr.indices, csr.indptr), shape=csr.shape)
        row_sums = np.asarray(expm1.sum(axis=1)).ravel()
    else:
        dense = np.asarray(matrix)
        largest = float(dense.max()) if dense.size else 0.0
        if largest >= LOG_MAX_VALUE:
            return False
        row_sums = np.concatenate([
            np.expm1(np.asarray(dense[start:start + BLOCK_ROWS], dtype=np.float64)).sum(axis=1)
            for start in range(0, dense.shape[0], BLOCK_ROWS)
        ]) if dense.shape[0] else np.zeros(0)
    nonzero = row_sums[row_sums > 0]
    if nonzero.size == 0:
        return False
    spread = (nonzero.max() - nonzero.min()) / np.median(nonzero)
    return bool(spread < LOG_SPREAD_TOLERANCE)


def _check_counts(matrix, allow_noninteger: bool) -> None:
    integer, minimum, maximum, fractional = _value_summary(matrix)
    if minimum < 0:
        raise ValueError(f"Input contains negative values (min={minimum:g}); raw counts must be non-negative")
    if integer:
        return
    if not allow_noninteger:
        raise ValueError(
            f"Input does not look like raw counts (min={minimum:g}, max={maximum:g}, "
            f"fractional fraction={fractional:.4g}); use --allow-noninteger only if these are raw counts"
        )
    if _looks_log_cp10k(matrix):
        raise ValueError(
            f"Input looks log-transformed (max={maximum:g}, expm1 row sums constant); "
            "--allow-noninteger does not accept logged matrices"
        )


def _normalise_panel(matrix, rows: list[dict[str, str]], panel: list[str]):
    """Sum mapped input columns as raw counts, then CP10k over the panel, then log1p. Returns float32 CSR."""
    panel_col = {gene: j for j, gene in enumerate(panel)}
    mapped = [(i, panel_col[row["target"]]) for i, row in enumerate(rows) if row["target"]]
    input_cols = np.array([i for i, _ in mapped], dtype=np.intp)
    projection = sparse.csr_matrix(
        (np.ones(len(mapped)), (np.arange(len(mapped), dtype=np.intp), np.array([j for _, j in mapped], dtype=np.intp))),
        shape=(len(mapped), len(panel)),
    )
    source = sparse.csr_matrix(matrix) if sparse.issparse(matrix) else np.asarray(matrix)
    blocks = []
    for start in range(0, source.shape[0], BLOCK_ROWS):
        # Select rows first, then the mapped columns, so only one block is copied at a time.
        block = source[start:start + BLOCK_ROWS][:, input_cols]
        if sparse.issparse(block):
            block = sparse.csr_matrix(block, dtype=np.float64)
        else:
            block = sparse.csr_matrix(np.asarray(block, dtype=np.float64))
        counts = sparse.csr_matrix(block @ projection)
        sums = np.asarray(counts.sum(axis=1)).ravel()
        factors = np.divide(10000.0, sums, out=np.zeros_like(sums), where=sums != 0)
        scaled = sparse.csr_matrix(sparse.diags(factors) @ counts)
        scaled.data = np.log1p(scaled.data)
        blocks.append(scaled.astype(np.float32))
    if not blocks:
        return sparse.csr_matrix((0, len(panel)), dtype=np.float32)
    return sparse.vstack(blocks, format="csr", dtype=np.float32)


def normalize(input_path: str | Path, panel_path: str | Path, out_path: str | Path, layer: str | None = None,
              fill_missing: bool = False, allow_noninteger: bool = False,
              mgi_dir: str | Path | None = None, report: str | Path | None = None):
    panel = read_panel(panel_path)
    data = ad.read_h5ad(input_path)
    matrix = _matrix(data, layer)
    _check_counts(matrix, allow_noninteger)
    names = [str(x) for x in data.var_names]
    rows, missing = resolve_names(names, panel, mgi_dir)
    _write_mapping(report, rows, missing)
    if missing and not fill_missing:
        raise ValueError(f"{len(missing)} panel genes are missing; pass --fill-missing zeros to fill them. First: {missing[:10]}")
    summary = _counts(rows)
    normalized = _normalise_panel(matrix, rows, panel)
    missing_set = set(missing)
    var = pd.DataFrame(
        {"filled_zero": [gene in missing_set for gene in panel]},
        index=pd.Index(panel, name=data.var_names.name or "gene"),
    )
    result = ad.AnnData(X=normalized, obs=data.obs.copy(), var=var)
    duplicates = Counter(row["target"] for row in rows if row["target"])
    result.uns["vec_normalise"] = {
        "version": VERSION, "run_date": date.today().isoformat(),
        "input_sha256": sha256(input_path), "panel_sha256": sha256(panel_path),
        "mgi": _mgi_provenance(_mgi_root(mgi_dir)), "mapping_counts": summary,
        "layer": layer or "X", "filled_missing": missing if fill_missing else [],
        "duplicate_targets_summed": {gene: int(n) for gene, n in duplicates.items() if n > 1},
    }
    result.uns["vec_normalise_mapping"] = _mapping_frame(rows, missing)
    result.write_h5ad(out_path, compression="gzip")
    return summary, missing, result.shape


# ---------------------------------------------------------------------------
# Release check
# ---------------------------------------------------------------------------

def _as_csr(matrix):
    if sparse.issparse(matrix):
        return sparse.csr_matrix(matrix)
    return sparse.csr_matrix(np.asarray(matrix))


def _logged_from_counts(counts):
    matrix = _as_csr(counts).astype(np.float64)
    sums = np.asarray(matrix.sum(axis=1)).ravel()
    factors = np.divide(10000.0, sums, out=np.zeros_like(sums), where=sums != 0)
    out = sparse.csr_matrix(sparse.diags(factors) @ matrix)
    out.data = np.log1p(out.data)
    return out


def verify_release(path: str | Path, panel_path: str | Path | None = None):
    data = ad.read_h5ad(path)
    X = _as_csr(data.X)
    if "counts" not in data.layers:
        sums = np.asarray(X.expm1().sum(axis=1)).ravel()
        quantiles = np.quantile(sums, [0, .5, .95, 1]) if sums.size else [0, 0, 0, 0]
        at_cp10k = abs(float(np.median(sums)) - 10000) < 1
        order_matches = list(map(str, data.var_names)) == read_panel(panel_path) if panel_path else None
        if at_cp10k and order_matches:
            implied_scope = "panel (stored genes match supplied panel and median expm1 row sum is 10000)"
        elif at_cp10k:
            implied_scope = "CP10k over stored var_names; panel vs all-gene scope is not identifiable from row sums alone"
        else:
            implied_scope = "not consistent with CP10k over stored var_names"
        return {"counts_layer": False, "rows": data.n_obs, "columns": data.n_vars,
                "expm1_row_sum_quantiles": quantiles.tolist(), "implied_scope": implied_scope,
                "panel_order_matches": order_matches, "delta_max": None}
    counts = data.layers["counts"]
    sums = np.asarray(_as_csr(counts).sum(axis=1)).ravel()
    expected = _logged_from_counts(counts)
    delta = expected - X
    max_delta = float(np.max(np.abs(delta.data))) if delta.nnz else 0.0
    result = {"counts_layer": True, "rows": data.n_obs, "columns": data.n_vars,
              "count_row_sum_quantiles": np.quantile(sums, [0, .5, .95, 1]).tolist() if sums.size else [0, 0, 0, 0],
              "delta_max": max_delta, "scope": "panel"}
    if panel_path:
        panel = read_panel(panel_path)
        result["panel_order_matches"] = list(map(str, data.var_names)) == panel
    return result


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    norm = sub.add_parser("normalise", help="resolve genes and write panel-ordered log CP10k")
    norm.add_argument("input")
    norm.add_argument("--panel", required=True)
    norm.add_argument("--out", required=True)
    norm.add_argument("--layer")
    norm.add_argument("--fill-missing", choices=["zeros"])
    norm.add_argument("--allow-noninteger", action="store_true")
    norm.add_argument("--mgi-dir")
    norm.add_argument("--report")
    resolve = sub.add_parser("resolve", help="report gene mappings without writing a normalized file")
    resolve.add_argument("input")
    resolve.add_argument("--panel", required=True)
    resolve.add_argument("--mgi-dir")
    resolve.add_argument("--report")
    verify = sub.add_parser("verify", help="check a release file against its raw counts layer")
    verify.add_argument("input")
    verify.add_argument("--panel")
    args = parser.parse_args(argv)
    try:
        if args.command == "normalise":
            summary, missing, shape = normalize(args.input, args.panel, args.out, args.layer,
                                                args.fill_missing == "zeros", args.allow_noninteger,
                                                args.mgi_dir, args.report)
            print(json.dumps({"shape": shape, "mapping_counts": summary, "missing": len(missing), "output": args.out}, indent=2))
        elif args.command == "resolve":
            data = ad.read_h5ad(args.input, backed="r")
            names = list(map(str, data.var_names))
            data.file.close()
            rows, missing = resolve_names(names, read_panel(args.panel), args.mgi_dir)
            _write_mapping(args.report, rows, missing)
            print(json.dumps({"mapping_counts": _counts(rows), "missing": len(missing), "missing_preview": missing[:20]}, indent=2))
        else:
            print(json.dumps(verify_release(args.input, args.panel), indent=2))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
