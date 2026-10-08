#!/usr/bin/env python3
from __future__ import annotations

import gzip
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
VALIDATION.mkdir(exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix="vec-external-real-"))
TESTED_ON = datetime.now(timezone.utc).date().isoformat()


def hash_file(path: Path) -> dict:
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
    return {"sha256": h.hexdigest(), "bytes": total, "filename": path.name}


def fetch(url: str, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    total = 0
    url = url.replace("ftp://ftp.ncbi.nlm.nih.gov/", "https://ftp.ncbi.nlm.nih.gov/")
    req = urllib.request.Request(url, headers={"User-Agent": "vec-external-catalog-validation/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r, dest.open("wb") as f:
        while True:
            chunk = r.read(8 * 1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            total += len(chunk)
    return {"url": url, "sha256": h.hexdigest(), "bytes": total, "filename": dest.name}


def run(*args: object) -> subprocess.CompletedProcess:
    cmd = [sys.executable, *map(str, args)]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if proc.returncode:
        raise RuntimeError(
            f"processor failed ({proc.returncode}): {' '.join(map(str, args))}\n"
            f"stdout: {proc.stdout.strip()}\nstderr: {proc.stderr.strip()}"
        )
    return proc


def write_manifest(name: str, payload: dict) -> None:
    payload = {"tested_on": TESTED_ON, **payload}
    (VALIDATION / f"{name}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def validate_gse247450() -> None:
    raw = WORK / "gse247450"
    urls = [
        "https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM7890nnn/GSM7890128/suppl/GSM7890128_E9.5_region_0_cell_by_gene.csv.gz",
        "https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM7890nnn/GSM7890128/suppl/GSM7890128_E9.5_region_0_cell_metadata.csv.gz",
    ]
    files = [fetch(url, raw / url.rsplit("/", 1)[-1]) for url in urls]
    matrix_path = raw / files[0]["filename"]
    meta_path = raw / files[1]["filename"]
    matrix = pd.read_csv(matrix_path, index_col=0)
    meta = pd.read_csv(meta_path, index_col=0)

    out_dir = WORK / "gse247450_out"
    proc = run(ROOT / "processors/process_gse247450.py", raw, "--task", "t2-heart", "--out-dir", out_dir)
    out = out_dir / "GSM7890128_E9.5_region_0.t2-heart.h5ad"
    result = ad.read_h5ad(out)
    provenance = json.loads(out.with_suffix(".provenance.json").read_text())

    write_manifest("gse247450_e9_5_region0", {
        "status": "real_release_processor_passed",
        "source": "GSE247450 / GSM7890128",
        "source_files": files,
        "command": "python processors/process_gse247450.py <raw_dir> --task t2-heart --out-dir <out_dir>",
        "processor_exit": proc.returncode,
        "processor_stdout": proc.stdout.strip(),
        "raw_matrix_shape_as_stored": list(matrix.shape),
        "raw_metadata_shape": list(meta.shape),
        "observed_metadata_columns": list(map(str, meta.columns)),
        "output_cells": int(result.n_obs),
        "output_genes": int(result.n_vars),
        "spatial_3d_present": "spatial_3D" in result.obsm,
        "provenance": provenance,
    })


def _parse_geo_family_soft(path: Path) -> dict[str, dict]:
    samples: dict[str, dict] = {}
    current = None
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("^SAMPLE = "):
                current = line.split("=", 1)[1].strip()
                samples[current] = {"accession": current, "supplementary_files": [], "characteristics": []}
                continue
            if current is None:
                continue
            if line.startswith("!Sample_title = "):
                samples[current]["title"] = line.split("=", 1)[1].strip()
            elif line.startswith("!Sample_source_name_ch1 = "):
                samples[current]["source_name"] = line.split("=", 1)[1].strip()
            elif line.startswith("!Sample_characteristics_ch1 = "):
                samples[current]["characteristics"].append(line.split("=", 1)[1].strip())
            elif line.startswith("!Sample_supplementary_file"):
                samples[current]["supplementary_files"].append(line.split("=", 1)[1].strip())
    return samples


def validate_gse282547_e14_5() -> None:
    """Discover and run one allowed E14.5 Visium sample from the real GEO release."""
    family_url = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE282nnn/GSE282547/soft/GSE282547_family.soft.gz"
    family_path = WORK / "GSE282547_family.soft.gz"
    family_source = fetch(family_url, family_path)
    samples = _parse_geo_family_soft(family_path)

    required = ["_matrix.mtx.gz", "_features.tsv.gz", "_barcodes.tsv.gz", "_tissue_positions_list.csv.gz"]
    candidates = []
    for gsm, sample in samples.items():
        haystack = " ".join([
            sample.get("title", ""), sample.get("source_name", ""),
            *sample.get("characteristics", []), *sample.get("supplementary_files", []),
        ])
        if not re.search(r"E14(?:[._ ]?5)", haystack, flags=re.IGNORECASE):
            continue
        files = sample.get("supplementary_files", [])
        if all(any(url.endswith(suffix) for url in files) for suffix in required):
            candidates.append((gsm, sample))

    if not candidates:
        e14_seen = {
            gsm: {"title": s.get("title"), "source_name": s.get("source_name"), "files": s.get("supplementary_files", [])}
            for gsm, s in samples.items()
            if re.search(r"E14(?:[._ ]?5)", " ".join([s.get("title", ""), s.get("source_name", "")]), flags=re.IGNORECASE)
        }
        raise RuntimeError(f"No E14.5 Visium sample with the four expected 10x files. E14.5 records: {e14_seen}")

    gsm, sample = candidates[0]
    raw = WORK / f"gse282547_{gsm}"
    source_files = []
    for suffix in required:
        url = next(url for url in sample["supplementary_files"] if url.endswith(suffix))
        source_files.append(fetch(url, raw / url.rsplit("/", 1)[-1]))

    out = WORK / f"{gsm}.E14.5.t2-heart.h5ad"
    proc = run(
        ROOT / "processors/process_gse282547_visium.py", raw,
        "--stage", "14.5", "--task", "t2-heart", "--out", out,
    )
    result = ad.read_h5ad(out)
    provenance = json.loads(out.with_suffix(".provenance.json").read_text())

    write_manifest("gse282547_e14_5_visium", {
        "status": "real_release_processor_passed",
        "source": "GSE282547 developing-heart atlas",
        "sample_accession": gsm,
        "sample_title": sample.get("title"),
        "sample_source_name": sample.get("source_name"),
        "sample_characteristics": sample.get("characteristics", []),
        "family_soft": family_source,
        "source_files": source_files,
        "candidate_samples_with_required_files": [x[0] for x in candidates],
        "command": "python processors/process_gse282547_visium.py <sample_dir> --stage 14.5 --task t2-heart --out <h5ad>",
        "processor_exit": proc.returncode,
        "processor_stdout": proc.stdout.strip(),
        "output_spots": int(result.n_obs),
        "output_genes": int(result.n_vars),
        "spatial_2d_present": "spatial_2D" in result.obsm,
        "spatial_3d_present": "spatial_3D" in result.obsm,
        "provenance": provenance,
    })


def validate_mouse_go() -> None:
    url = "https://current.geneontology.org/annotations/gaf/MOUSE-mod.gaf.gz"
    src = WORK / "MOUSE-mod.gaf.gz"
    source = fetch(url, src)
    genes = WORK / "go_probe_genes.txt"
    genes.write_text("Gata4\nCtnnb1\nMab21l2\n", encoding="utf-8")
    out = WORK / "mouse_go_probe.csv"
    proc = run(ROOT / "processors/prepare_mouse_go.py", src, "--gene-list", genes, "--out", out)
    table = pd.read_csv(out)
    write_manifest("mouse_go", {
        "status": "real_release_processor_passed",
        "source": "Mouse Gene Ontology GAF",
        "source_files": [source],
        "command": "python processors/prepare_mouse_go.py MOUSE-mod.gaf.gz --gene-list <3-gene probe> --out <csv>",
        "probe_genes": ["Gata4", "Ctnnb1", "Mab21l2"],
        "processor_exit": proc.returncode,
        "processor_stdout": proc.stdout.strip(),
        "output_rows": int(len(table)),
        "genes_found": sorted(table["gene"].astype(str).unique().tolist()) if len(table) else [],
        "evidence_codes_observed": sorted(table["evidence"].astype(str).unique().tolist()) if len(table) else [],
    })


def probe_sc3d_release() -> None:
    api = "https://api.figshare.com/v2/articles/21695879/versions/1/files"
    req = urllib.request.Request(api, headers={"User-Agent": "vec-external-catalog-validation/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        files = json.load(r)
    h5ads = [f for f in files if str(f.get("name", "")).lower().endswith(".h5ad")]
    if not h5ads:
        write_manifest("sc3d_e9_0", {
            "source": "sc3D E9.0 Figshare", "status": "no_h5ad_found_via_figshare_api",
            "api": api, "files": files,
        })
        return
    item = h5ads[0]
    size = int(item.get("size") or 0)
    if size > 2_500_000_000:
        write_manifest("sc3d_e9_0", {
            "source": "sc3D E9.0 Figshare",
            "status": "not_run_release_too_large_for_hosted_validator",
            "figshare_file": item,
        })
        return
    src = WORK / str(item["name"])
    source = fetch(str(item["download_url"]), src)
    out_dir = WORK / "sc3d_out"
    proc = run(ROOT / "processors/process_sc3d.py", src, "--task", "t2-heart", "--stage", "9.0", "--out-dir", out_dir)
    outputs = list(out_dir.glob("*.h5ad"))
    if len(outputs) != 1:
        raise RuntimeError(f"Expected one sc3D output, got {outputs}")
    result = ad.read_h5ad(outputs[0])
    provenance = json.loads(outputs[0].with_suffix(".provenance.json").read_text())
    write_manifest("sc3d_e9_0", {
        "status": "real_release_processor_passed",
        "source": "sc3D E9.0 Figshare",
        "figshare_file": item,
        "source_files": [source],
        "command": "python processors/process_sc3d.py <E9.0 h5ad> --task t2-heart --stage 9.0 --out-dir <out_dir>",
        "processor_exit": proc.returncode,
        "processor_stdout": proc.stdout.strip(),
        "output_cells": int(result.n_obs),
        "output_genes": int(result.n_vars),
        "spatial_3d_present": "spatial_3D" in result.obsm,
        "provenance": provenance,
    })


def record_extended_mouse_atlas_constraint() -> None:
    write_manifest("extended_mouse_atlas", {
        "source": "Extended Mouse Atlas",
        "status": "not_real_run_validated",
        "reason": "official downloadable package is a 25 GB tarball; not downloaded by the hosted validator",
        "release_index": "https://bioinformatics.stemcells.cam.ac.uk/rlh60/Supplemental/ExtendedMouseAtlas/",
        "advertised_archive": "ExtendedMouseAtlas.tar.gz",
        "advertised_size": "25G",
    })


def record_tabula_muris_demotion() -> None:
    write_manifest("tabula_muris", {
        "source": "Tabula Muris",
        "status": "demoted_after_access_failure",
        "reason": "developmentally distant, and advertised processed-object download was not reproducible from the hosted validator",
        "observed_access_attempts": [
            {"route": "legacy bucket czbiohub-tabula-muris", "result": "HTTP/S3 403"},
            {"route": "Open Data Registry bucket czb-tabula-muris", "result": "HeadObject 403 Forbidden"},
        ],
        "recommendation": "Prefer the allowed E14.5+ developing-heart atlas for task-relevant later-stage priors.",
    })


def main() -> None:
    print("workdir", WORK)
    checks = [
        ("gse247450_e9_5_region0", validate_gse247450),
        ("gse282547_e14_5_visium", validate_gse282547_e14_5),
        ("mouse_go", validate_mouse_go),
        ("sc3d_e9_0", probe_sc3d_release),
    ]
    failures = []
    for name, fn in checks:
        print(f"\n--- validating {name} ---")
        try:
            fn()
        except Exception as exc:
            failures.append((name, repr(exc)))
            write_manifest(name, {
                "status": "validation_error",
                "source": name,
                "error": repr(exc),
            })
            print(f"FAILED {name}: {exc}", file=sys.stderr)

    record_extended_mouse_atlas_constraint()
    record_tabula_muris_demotion()
    print("\nwrote manifests:")
    for p in sorted(VALIDATION.glob("*.json")):
        print(" -", p.relative_to(ROOT))

    if failures:
        print("\nvalidation failures:", file=sys.stderr)
        for name, err in failures:
            print(f" - {name}: {err}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
