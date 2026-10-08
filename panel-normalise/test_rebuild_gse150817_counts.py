import gzip
import importlib.util
from pathlib import Path

import anndata as ad
import numpy as np

SCRIPT = Path(__file__).resolve().parent / "scripts" / "rebuild_gse150817_counts.py"
spec = importlib.util.spec_from_file_location("rebuild_gse150817_counts", SCRIPT)
rebuild_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rebuild_module)


def test_rebuild_keeps_requested_cells_in_list_order(tmp_path):
    source = tmp_path / "table.tsv.gz"
    with gzip.open(source, "wt") as handle:
        handle.write("\tc1\tc2\tc3\n")
        handle.write("g1\t1\t0\t2\n")
        handle.write("g2\t0\t3\t0\n")
        handle.write("g3\t5\t0\t0\n")
    cells = tmp_path / "cells.txt"
    cells.write_text("c3\nc1\n")
    out = tmp_path / "raw.h5ad"
    rebuild_module.rebuild(source, out, rebuild_module.read_cell_list(cells))
    data = ad.read_h5ad(out)
    assert list(data.obs_names) == ["c3", "c1"]
    assert list(data.var_names) == ["g1", "g2", "g3"]
    assert data.X.toarray().tolist() == [[2, 0, 0], [1, 0, 5]]
    assert data.uns["source"]["nonzero_entries"] == 3
    assert data.X.dtype == np.int32


def test_rebuild_refuses_absent_cells(tmp_path):
    source = tmp_path / "table.tsv.gz"
    with gzip.open(source, "wt") as handle:
        handle.write("\tc1\n")
        handle.write("g1\t1\n")
    try:
        rebuild_module.rebuild(source, tmp_path / "raw.h5ad", ["c9"])
    except ValueError as exc:
        assert "absent" in str(exc)
    else:
        raise AssertionError("absent cell was accepted")
