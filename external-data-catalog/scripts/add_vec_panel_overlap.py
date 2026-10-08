#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import urllib.request
from pathlib import Path

import anndata as ad
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
VECKIT_COMMIT = "46d41e63f42a9aab815db20b742feeccd249cb17"
PANEL_URL = f"https://raw.githubusercontent.com/aristoteleo/veckit/{VECKIT_COMMIT}/data/sample_heart_9.5.h5ad"


def download(url: str, path: Path) -> None:
    url = url.replace("ftp://ftp.ncbi.nlm.nih.gov/", "https://ftp.ncbi.nlm.nih.gov/")
    req = urllib.request.Request(url, headers={"User-Agent": "vec-external-catalog-overlap/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r, path.open("wb") as f:
        while True:
            block = r.read(8 * 1024 * 1024)
            if not block:
                break
            f.write(block)


def update_manifest(path: Path, panel: list[str], source_genes: set[str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    found = [g for g in panel if g in source_genes]
    missing = [g for g in panel if g not in source_genes]
    payload["vec_heart_panel"] = {
        "source": f"veckit@{VECKIT_COMMIT}:data/sample_heart_9.5.h5ad",
        "panel_genes": len(panel),
        "genes_found": len(found),
        "genes_missing": len(missing),
        "missing_gene_symbols": missing,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vec-panel-overlap-") as td:
        td = Path(td)
        panel_path = td / "sample_heart_9.5.h5ad"
        download(PANEL_URL, panel_path)
        panel = list(map(str, ad.read_h5ad(panel_path, backed="r").var_names))
        if len(panel) < 100:
            raise RuntimeError(f"Unexpectedly small VEC heart panel: {len(panel)}")

        gse247 = VALIDATION / "gse247450_e9_5_region0.json"
        if gse247.exists():
            payload = json.loads(gse247.read_text(encoding="utf-8"))
            if payload.get("status") == "real_release_processor_passed":
                matrix_info = next(x for x in payload["source_files"] if "cell_by_gene" in x["filename"])
                matrix_path = td / matrix_info["filename"]
                download(matrix_info["url"], matrix_path)
                # This validated release is cells x genes. Reading only the header avoids
                # turning a gene-overlap audit into another full processing pass.
                columns = pd.read_csv(matrix_path, nrows=0, index_col=0).columns.astype(str)
                update_manifest(gse247, panel, set(columns))

        gse282 = VALIDATION / "gse282547_e14_5_visium.json"
        if gse282.exists():
            payload = json.loads(gse282.read_text(encoding="utf-8"))
            if payload.get("status") == "real_release_processor_passed":
                features_info = next(x for x in payload["source_files"] if "features.tsv" in x["filename"])
                features_path = td / features_info["filename"]
                download(features_info["url"], features_path)
                features = pd.read_csv(features_path, sep="\t", header=None, compression="infer")
                source_genes = set(features.iloc[:, 1].astype(str) if features.shape[1] >= 2 else features.iloc[:, 0].astype(str))
                update_manifest(gse282, panel, source_genes)

        print(f"VEC heart panel: {len(panel)} genes")
        for name in ["gse247450_e9_5_region0.json", "gse282547_e14_5_visium.json"]:
            path = VALIDATION / name
            if path.exists():
                info = json.loads(path.read_text()).get("vec_heart_panel")
                if info:
                    print(name, info["genes_found"], "/", info["panel_genes"])


if __name__ == "__main__":
    main()
