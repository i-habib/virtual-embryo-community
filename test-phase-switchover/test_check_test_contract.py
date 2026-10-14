"""Tests for check_test_contract.py with tiny synthetic .h5ad files and a fake index.

No network: the index and gene lists are written into tmp_path and passed with
--index and --panels-dir.
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_test_contract as ctc  # noqa: E402

anndata = pytest.importorskip("anndata")
sp = pytest.importorskip("scipy.sparse")

GENES_A = ["Tnnt2", "Myh6", "Nkx2-5", "Gata4", "Isl1"]
GENES_B = ["Sox17", "Foxa2", "T", "Mixl1"]


def _sha(genes):
    return hashlib.sha256("\n".join(genes).encode()).hexdigest()[:16]


def _board(key, genes_file, genes, **extra):
    b = {
        "key": key,
        "task": key.split(":")[0],
        "split": "test",
        "n_genes": len(genes),
        "genes_file": genes_file,
        "genes_sha256": _sha(genes),
        "needs_coords": False,
        "obs_required": [],
        "obsm_required": [],
        "min_cells": 3,
        "max_cells": 10,
    }
    b.update(extra)
    return b


@pytest.fixture
def world(tmp_path):
    """A fake index with a validation-style board and a test-style board.

    "T3:beta_catenin:test" is not in the real index, which is the point: the
    checker has to work for keys it has never seen.
    """
    (tmp_path / "a.genes.txt").write_text("\n".join(GENES_A) + "\n")
    (tmp_path / "b.genes.txt").write_text("\n".join(GENES_B) + "\n")
    boards = {
        "T1:test": _board("T1:test", "a.genes.txt", GENES_A),
        "T3:beta_catenin:test": _board(
            "T3:beta_catenin:test", "b.genes.txt", GENES_B,
            needs_coords=True, obsm_required=["spatial_3D"], target_ko="ctnnb1"),
    }
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps(boards))
    return {"dir": tmp_path, "index": idx, "boards": boards}


def _write(path, genes, n=5, X=None, obsm=None, sparse=False):
    if X is None:
        X = np.abs(np.random.default_rng(0).normal(size=(n, len(genes)))).astype("float32")
    if sparse:
        X = sp.csr_matrix(X)
    adata = anndata.AnnData(
        X=X,
        obs=pd.DataFrame(index=[f"c{i}" for i in range(X.shape[0])]),
        var=pd.DataFrame(index=genes),
        obsm=obsm or {},
    )
    adata.write_h5ad(path)
    return path


def _run(world, *args):
    argv = ["--index", str(world["index"]), "--panels-dir", str(world["dir"])] + list(args)
    return ctc.main(argv)


def test_list_prints_every_board_key(world, capsys):
    assert _run(world, "--list") == 0
    out = capsys.readouterr().out
    assert "T1:test" in out
    assert "T3:beta_catenin:test" in out


def test_valid_file_passes_for_a_test_style_board(world, capsys):
    f = _write(world["dir"] / "ok.h5ad", GENES_B, n=5,
               obsm={"spatial_3D": np.zeros((5, 3), dtype="float32")})
    assert _run(world, str(f), "T3:beta_catenin:test") == 0
    assert "PASS" in capsys.readouterr().out


def test_valid_file_passes_for_a_plain_board(world):
    f = _write(world["dir"] / "ok1.h5ad", GENES_A, n=4)
    assert _run(world, str(f), "T1:test") == 0


def test_sparse_X_is_accepted(world):
    f = _write(world["dir"] / "sp.h5ad", GENES_A, n=4, sparse=True)
    assert _run(world, str(f), "T1:test") == 0


def test_wrong_gene_order_fails(world, capsys):
    f = _write(world["dir"] / "order.h5ad", list(reversed(GENES_A)), n=4)
    assert _run(world, str(f), "T1:test") == 1
    assert "gene names or order differ" in capsys.readouterr().out


def test_gene_count_mismatch_fails(world, capsys):
    f = _write(world["dir"] / "short.h5ad", GENES_A[:3], n=4)
    assert _run(world, str(f), "T1:test") == 1
    assert "gene count 3, panel has 5" in capsys.readouterr().out


@pytest.mark.parametrize("n", [2, 11])
def test_cell_count_outside_bounds_fails(world, n):
    f = _write(world["dir"] / f"n{n}.h5ad", GENES_A, n=n)
    assert _run(world, str(f), "T1:test") == 1


def test_missing_required_obsm_fails(world, capsys):
    f = _write(world["dir"] / "noobsm.h5ad", GENES_B, n=4)
    assert _run(world, str(f), "T3:beta_catenin:test") == 1
    assert "obsm['spatial_3D'] missing" in capsys.readouterr().out


def test_obsm_with_two_columns_fails(world, capsys):
    f = _write(world["dir"] / "two.h5ad", GENES_B, n=4,
               obsm={"spatial_3D": np.zeros((4, 2), dtype="float32")})
    assert _run(world, str(f), "T3:beta_catenin:test") == 1
    assert "(at least 3 needed)" in capsys.readouterr().out


def test_obsm_with_wrong_row_count_fails(world, capsys):
    # AnnData refuses to write a mismatched obsm array, so write a valid file
    # and replace the dataset underneath it with h5py. AnnData also refuses to
    # read that file, so the checker reports a read error (exit 2). The row
    # check in check_file is a second line of defence for other readers.
    h5py = pytest.importorskip("h5py")
    f = _write(world["dir"] / "rows.h5ad", GENES_B, n=4,
               obsm={"spatial_3D": np.zeros((4, 3), dtype="float32")})
    with h5py.File(f, "r+") as h:
        del h["obsm/spatial_3D"]
        h.create_dataset("obsm/spatial_3D", data=np.zeros((3, 3), dtype="float32"))
    assert _run(world, str(f), "T3:beta_catenin:test") == 2
    assert "could not read" in capsys.readouterr().err


def test_negative_X_fails(world):
    X = np.ones((4, len(GENES_A)), dtype="float32")
    X[1, 2] = -0.5
    f = _write(world["dir"] / "neg.h5ad", GENES_A, X=X)
    assert _run(world, str(f), "T1:test") == 1


def test_nan_X_fails(world, capsys):
    X = np.ones((4, len(GENES_A)), dtype="float32")
    X[0, 0] = np.nan
    f = _write(world["dir"] / "nan.h5ad", GENES_A, X=X)
    assert _run(world, str(f), "T1:test") == 1
    assert "X finite" in capsys.readouterr().out


def test_unknown_board_key_exits_2(world, capsys):
    f = _write(world["dir"] / "any.h5ad", GENES_A, n=4)
    assert _run(world, str(f), "T9:nope") == 2
    assert "not in the index" in capsys.readouterr().err


def test_gene_list_that_does_not_match_index_hash_fails(world, capsys):
    boards = world["boards"]
    boards["T1:test"]["genes_sha256"] = "0" * 16
    world["index"].write_text(json.dumps(boards))
    f = _write(world["dir"] / "hash.h5ad", GENES_A, n=4)
    assert _run(world, str(f), "T1:test") == 1
    assert "genes_sha256" in capsys.readouterr().out


def test_missing_gene_file_exits_2(world):
    (world["dir"] / "a.genes.txt").unlink()
    f = _write(world["dir"] / "nogenes.h5ad", GENES_A, n=4)
    assert _run(world, str(f), "T1:test") == 2
