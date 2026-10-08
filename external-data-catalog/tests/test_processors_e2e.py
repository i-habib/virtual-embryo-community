from __future__ import annotations

import csv
import gzip
import json
import subprocess
import sys
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.io import mmwrite

ROOT = Path(__file__).resolve().parents[1]


def run_processor(*args):
    return subprocess.run(
        [sys.executable, *map(str, args)],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def write_gene_list(path: Path):
    path.write_text("G1\nG3\n", encoding="utf-8")


def tiny_adata(stages=None):
    obs = pd.DataFrame(index=["c1", "c2", "c3"])
    if stages is not None:
        obs["stage"] = stages
    a = ad.AnnData(
        X=np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.float32),
        obs=obs,
    )
    a.var_names = ["G1", "G2", "G3"]
    return a


def test_extended_mouse_atlas_end_to_end(tmp_path):
    src = tmp_path / "embryo_complete.h5ad"
    out = tmp_path / "ema.t2-heart.h5ad"
    genes = tmp_path / "genes.txt"
    write_gene_list(genes)
    tiny_adata(["E8.25", "E8.5", "E8.75"]).write_h5ad(src)

    run_processor(
        ROOT / "processors/process_extended_mouse_atlas.py",
        src, "--task", "t2-heart", "--gene-list", genes, "--out", out,
    )
    result = ad.read_h5ad(out)
    assert result.shape == (2, 2)
    assert list(result.var_names) == ["G1", "G3"]
    assert sorted(result.obs["vec_stage"].tolist()) == [8.25, 8.75]
    prov = json.loads(out.with_suffix(".provenance.json").read_text())
    assert prov["protected_stages_removed"] == [8.5]
    assert prov["stage_filter_applied"] is True


def test_sc3d_end_to_end_and_t3_warning(tmp_path):
    src = tmp_path / "E9_0_demo.h5ad"
    out_dir = tmp_path / "sc3d"
    genes = tmp_path / "genes.txt"
    write_gene_list(genes)
    a = tiny_adata()
    a.obsm["spatial"] = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 1]], dtype=np.float32)
    a.write_h5ad(src)

    run_processor(
        ROOT / "processors/process_sc3d.py",
        src, "--task", "t2-heart", "--gene-list", genes, "--out-dir", out_dir,
    )
    out = out_dir / "E9_0_demo.t2-heart.h5ad"
    result = ad.read_h5ad(out)
    assert result.shape == (3, 2)
    assert "spatial_3D" in result.obsm
    prov = json.loads(out.with_suffix(".provenance.json").read_text())
    assert prov["spatial_source"] == "obsm:spatial"

    t3_dir = tmp_path / "sc3d_t3"
    proc = run_processor(
        ROOT / "processors/process_sc3d.py",
        src, "--task", "t3", "--out-dir", t3_dir,
    )
    assert "T3_GENOTYPE_NOT_AUDITED" in proc.stderr
    t3_prov = json.loads((t3_dir / "E9_0_demo.t3.provenance.json").read_text())
    assert t3_prov["t3_genotype_audit"] == "not_audited"


def test_gse247450_end_to_end_without_inventing_3d(tmp_path):
    raw = tmp_path / "gse"
    raw.mkdir()
    genes = tmp_path / "genes.txt"
    write_gene_list(genes)
    key = "GSM7890128_E9.5_region_0"

    # Deliberately gene x cell to exercise orientation detection.
    pd.DataFrame(
        [[1, 2], [3, 4], [5, 6]],
        index=["G1", "G2", "G3"],
        columns=["cellA", "cellB"],
    ).to_csv(raw / f"{key}_cell_by_gene.csv")
    pd.DataFrame(
        {"center_x": [1.0, 2.0], "center_y": [3.0, 4.0], "volume": [10.0, 11.0]},
        index=["cellA", "cellB"],
    ).to_csv(raw / f"{key}_cell_metadata.csv")

    out_dir = tmp_path / "gse_out"
    run_processor(
        ROOT / "processors/process_gse247450.py",
        raw, "--task", "t2-heart", "--gene-list", genes, "--out-dir", out_dir,
    )
    out = out_dir / f"{key}.t2-heart.h5ad"
    result = ad.read_h5ad(out)
    assert result.shape == (2, 2)
    assert "spatial_3D" not in result.obsm
    prov = json.loads(out.with_suffix(".provenance.json").read_text())
    assert prov["spatial_source"] is None
    assert "center_x" in prov["observed_metadata_columns"]


def _gzip_file(src: Path, dst: Path):
    with src.open("rb") as f_in, gzip.open(dst, "wb") as f_out:
        f_out.write(f_in.read())


def test_gse282547_visium_end_to_end_keeps_2d_explicit(tmp_path):
    raw = tmp_path / "visium"
    raw.mkdir()
    prefix = "GSM_TEST_E14_5"

    matrix_plain = raw / "matrix.mtx"
    # Matrix Market is genes x spots, as in 10x output.
    mmwrite(matrix_plain, sparse.coo_matrix(np.array([[1, 0], [2, 3], [0, 4]], dtype=np.int32)))
    _gzip_file(matrix_plain, raw / f"{prefix}_matrix.mtx.gz")
    matrix_plain.unlink()

    with gzip.open(raw / f"{prefix}_features.tsv.gz", "wt", encoding="utf-8") as f:
        f.write("ENSG1\tG1\tGene Expression\nENSG2\tG2\tGene Expression\nENSG3\tG3\tGene Expression\n")
    with gzip.open(raw / f"{prefix}_barcodes.tsv.gz", "wt", encoding="utf-8") as f:
        f.write("spotA\nspotB\n")
    with gzip.open(raw / f"{prefix}_tissue_positions_list.csv.gz", "wt", encoding="utf-8") as f:
        f.write("spotA,1,4,5,100.0,200.0\nspotB,1,6,7,110.0,210.0\n")

    genes = tmp_path / "genes.txt"
    write_gene_list(genes)
    out = tmp_path / "e14_5.t2-heart.h5ad"
    run_processor(
        ROOT / "processors/process_gse282547_visium.py",
        raw, "--stage", "14.5", "--task", "t2-heart", "--gene-list", genes, "--out", out,
    )
    result = ad.read_h5ad(out)
    assert result.shape == (2, 2)
    assert list(result.var_names) == ["G1", "G3"]
    assert "spatial_2D" in result.obsm
    assert "spatial_3D" not in result.obsm
    assert np.allclose(result.obsm["spatial_2D"], [[200.0, 100.0], [210.0, 110.0]])
    prov = json.loads(out.with_suffix(".provenance.json").read_text())
    assert prov["stage"] == 14.5
    assert prov["spatial_2d_present"] is True
    assert prov["spatial_3d_present"] is False


def test_tabula_muris_end_to_end(tmp_path):
    src = tmp_path / "TM_droplet_mat.h5ad"
    meta = tmp_path / "TM_droplet_metadata.csv"
    out = tmp_path / "tabula_heart.h5ad"
    genes = tmp_path / "genes.txt"
    write_gene_list(genes)
    a = tiny_adata()
    a.write_h5ad(src)
    pd.DataFrame(
        {"tissue": ["Heart", "Liver", "Heart"]},
        index=["c1", "c2", "c3"],
    ).to_csv(meta)

    run_processor(
        ROOT / "processors/process_tabula_muris.py",
        src, "--metadata", meta, "--tissue", "heart", "--gene-list", genes, "--out", out,
    )
    result = ad.read_h5ad(out)
    assert result.shape == (2, 2)
    assert set(result.obs["tissue"].astype(str)) == {"Heart"}


def test_mouse_go_end_to_end(tmp_path):
    gaf = tmp_path / "mouse.gaf"
    genes = tmp_path / "genes.txt"
    out = tmp_path / "mouse_go.csv"
    write_gene_list(genes)
    rows = [
        ["MGI", "MGI:1", "G1", "", "GO:0000001", "PMID:1", "IDA", "", "P", "Gene one", "", "protein", "taxon:10090", "20260101", "MGI", "", ""],
        ["MGI", "MGI:3", "G3", "", "GO:0000003", "GO_REF:1", "IEA", "", "F", "Gene three", "", "protein", "taxon:10090", "20260101", "MGI", "", ""],
    ]
    with gaf.open("w", encoding="utf-8", newline="") as f:
        f.write("!gaf-version: 2.2\n")
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerows(rows)

    run_processor(
        ROOT / "processors/prepare_mouse_go.py",
        gaf, "--gene-list", genes, "--exclude-iea", "--out", out,
    )
    result = pd.read_csv(out)
    assert result["gene"].tolist() == ["G1"]
    assert result["evidence"].tolist() == ["IDA"]
