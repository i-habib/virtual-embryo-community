import json

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

from vec_counts import DEFAULT_TOL, main, recover, roundtrip, sha256


def _logged(counts, dtype=np.float32, scale=10_000.0, denominator=None):
    """CP10k-style log1p of integer counts, rounded to dtype and stored sparsely."""
    counts = np.asarray(counts, dtype=np.float64)
    if denominator is None:
        totals = counts.sum(axis=1, keepdims=True)
    else:
        totals = np.full((counts.shape[0], 1), float(denominator))
    scaled = np.divide(scale * counts, totals, out=np.zeros_like(counts), where=totals != 0)
    return sparse.csr_matrix(np.log1p(scaled).astype(dtype))


def _write(path, X, names=None, obs=None):
    n, p = X.shape
    obs = pd.DataFrame(index=[f"cell{i}" for i in range(n)]) if obs is None else obs
    ad.AnnData(X=X, obs=obs,
               var=pd.DataFrame(index=names or [f"gene{i}" for i in range(p)])).write_h5ad(path)


def test_csc_float32_and_explicit_zeros_recover_exactly(tmp_path):
    counts = np.array([[1, 3, 0, 5], [0, 2, 3, 0], [7, 0, 1, 2]], dtype=np.int32)
    logged = _logged(counts).tocsc()
    logged.data = np.append(logged.data, np.float32(0))
    logged.indices = np.append(logged.indices, np.int32(1))
    logged.indptr[-1] += 1
    inp, out = tmp_path / "input.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, logged)
    report = recover(inp, out)
    result = ad.read_h5ad(out)
    assert sparse.isspmatrix_csr(result.X)
    np.testing.assert_array_equal(result.X.toarray(), counts)
    assert report["explicit_zeros_dropped"] == 1
    assert report["fraction_residual_below_tol"] == 1


def test_cell_without_count_one_uses_smallest_count(tmp_path):
    counts = np.array([[2, 3, 0], [1, 3, 5]], dtype=np.int32)
    inp, out = tmp_path / "input.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts).tocsc())
    report = recover(inp, out)
    result = ad.read_h5ad(out)
    np.testing.assert_array_equal(result.X.toarray(), counts)
    assert report["cells_needing_smallest_count_gt_1"] == 1
    assert report["smallest_count_histogram"]["2"] == 1
    assert list(result.obs["recovery_smallest_count"]) == [2, 1]


def test_smallest_count_above_five_fails(tmp_path):
    # Counts 6 and 7 need an assumed smallest count of 6, which is outside 1..5.
    counts = np.array([[6, 7], [1, 2]], dtype=np.int32)
    inp, out = tmp_path / "input.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts))
    with pytest.raises(ValueError, match="failed integer recovery"):
        recover(inp, out)
    assert not out.exists()
    report = json.loads((tmp_path / "recovered.h5ad.json").read_text())
    assert report["failing_cell_indices"] == [0]


def test_all_zero_cell_flagged_and_zero_library(tmp_path):
    counts = np.array([[0, 0, 0], [1, 2, 3]], dtype=np.int32)
    inp, out = tmp_path / "input.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts))
    report = recover(inp, out)
    result = ad.read_h5ad(out)
    assert report["all_zero_cells"] == [0]
    assert result.obs["library_size"].iloc[0] == 0
    assert result.obs["recovery_smallest_count"].iloc[0] == 0
    np.testing.assert_array_equal(result.X.toarray(), counts)


def test_dense_input(tmp_path):
    counts = np.array([[1, 1], [2, 5]], dtype=np.int32)
    inp, out = tmp_path / "dense.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts).toarray())
    recover(inp, out)
    np.testing.assert_array_equal(ad.read_h5ad(out).X.toarray(), counts)


def test_noisy_input_fails_instead_of_silent_rounding(tmp_path):
    counts = np.array([[1, 7], [2, 4]], dtype=np.int32)
    logged = _logged(counts).tolil()
    logged[0, 1] += 0.02
    inp, out = tmp_path / "noisy.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, logged.tocsr())
    with pytest.raises(ValueError, match="failed integer recovery"):
        recover(inp, out)
    assert not out.exists()
    report = json.loads((tmp_path / "recovered.h5ad.json").read_text())
    assert report["failing_cell_indices"] == [0]


def test_roundtrip_float32_precision(tmp_path):
    counts = np.array([[1, 10, 0], [4, 0, 8]], dtype=np.int32)
    original, recovered = tmp_path / "original.h5ad", tmp_path / "recovered.h5ad"
    _write(original, _logged(counts).tocsc())
    recover(original, recovered)
    report = roundtrip(recovered, original, chunk_rows=1)
    assert report["max_abs_delta"] < 1e-6


def test_large_count_survives_float32_storage(tmp_path):
    # Here the float32 storage error on the count of 5000 is about 1.4e-3 counts, which an
    # absolute tolerance of 1e-3 rejected. The relative bound accepts it.
    counts = np.array([[1, 5000, 2, 0, 7, 1]], dtype=np.int32)
    logged = _logged(counts)
    v = np.expm1(logged.data.astype(np.float64))
    assert np.max(np.abs(v / v.min() - np.rint(v / v.min()))) > 1e-3
    inp, out = tmp_path / "big.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, logged)
    recover(inp, out)
    np.testing.assert_array_equal(ad.read_h5ad(out).X.toarray(), counts)


def test_tolerance_must_be_below_half_and_positive(tmp_path):
    inp = tmp_path / "input.h5ad"
    _write(inp, _logged([[1, 2]]))
    for bad in (0.0, -1e-3, 0.5, 0.7):
        with pytest.raises(ValueError, match="0 < tol < 0.5"):
            recover(inp, tmp_path / "out.h5ad", tol=bad)


def test_loose_tolerance_is_refused_for_large_counts(tmp_path):
    # With tol = 0.3, a count near 2000 would accept values 600 counts away from an integer.
    inp = tmp_path / "input.h5ad"
    _write(inp, _logged([[1, 2000]]))
    with pytest.raises(ValueError, match="failed integer recovery"):
        recover(inp, tmp_path / "out.h5ad", tol=0.3)


def test_log1p_cpm_input_fails_cp10k_check(tmp_path):
    counts = np.array([[1, 3, 5], [2, 2, 6]], dtype=np.int32)
    inp, out = tmp_path / "cpm.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts, scale=1e6))
    with pytest.raises(ValueError, match="CP10k"):
        recover(inp, out)
    assert not out.exists()


def test_subset_denominator_fails_cp10k_check(tmp_path):
    # The normalization total is the sum of only the first two genes, not all four.
    counts = np.array([[1, 2, 3, 4]], dtype=np.int32)
    inp, out = tmp_path / "subset.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts, denominator=3))
    with pytest.raises(ValueError, match="CP10k"):
        recover(inp, out)
    report = json.loads((tmp_path / "recovered.h5ad.json").read_text())
    assert report["cp10k_check"]["failing_cell_indices"] == [0]
    assert report["cp10k_check"]["max_abs_sum_minus_library"] == pytest.approx(7.0)


def test_cp10k_check_passes_on_full_normalization(tmp_path):
    counts = np.array([[1, 2, 3, 4], [0, 5, 0, 9]], dtype=np.int32)
    inp, out = tmp_path / "input.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts))
    report = recover(inp, out)
    assert report["cp10k_check"]["failing_cell_indices"] == []
    assert report["cp10k_check"]["max_rel_sum_minus_library"] < 1e-6


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_nonfinite_input_is_a_clean_error(tmp_path, bad):
    logged = _logged([[1, 2, 3]]).tocsr()
    logged.data[0] = bad
    inp = tmp_path / "bad.h5ad"
    _write(inp, logged)
    with pytest.raises(ValueError, match="non-finite"):
        recover(inp, tmp_path / "out.h5ad")


def test_negative_input_is_a_clean_error(tmp_path):
    logged = _logged([[1, 2, 3]]).tocsr()
    logged.data[0] = -0.5
    inp = tmp_path / "neg.h5ad"
    _write(inp, logged)
    with pytest.raises(ValueError, match="negative"):
        recover(inp, tmp_path / "out.h5ad")


def test_cli_reports_errors_without_traceback(tmp_path, capsys):
    logged = _logged([[1, 2, 3]]).tocsr()
    logged.data[0] = np.nan
    inp = tmp_path / "bad.h5ad"
    _write(inp, logged)
    code = main(["recover", str(inp), str(tmp_path / "out.h5ad")])
    captured = capsys.readouterr()
    assert code != 0
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err
    missing = main(["recover", str(tmp_path / "nope.h5ad"), str(tmp_path / "out.h5ad")])
    assert missing != 0
    assert "Traceback" not in capsys.readouterr().err


def test_existing_output_is_not_overwritten_without_force(tmp_path):
    counts = np.array([[1, 2], [3, 1]], dtype=np.int32)
    inp, out = tmp_path / "input.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts))
    recover(inp, out)
    with pytest.raises(ValueError, match="already exists"):
        recover(inp, out)
    recover(inp, out, force=True)
    np.testing.assert_array_equal(ad.read_h5ad(out).X.toarray(), counts)


def test_existing_obs_columns_are_protected(tmp_path):
    counts = np.array([[1, 2]], dtype=np.int32)
    obs = pd.DataFrame({"library_size": [1.0]}, index=["cell0"])
    inp, out = tmp_path / "input.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts), obs=obs)
    with pytest.raises(ValueError, match="already has"):
        recover(inp, out)
    assert not out.exists()
    recover(inp, out, force=True)
    assert ad.read_h5ad(out).obs["library_size"].iloc[0] != 1.0


def test_provenance_records_input_name_and_hash(tmp_path):
    counts = np.array([[1, 2], [3, 1]], dtype=np.int32)
    inp, out = tmp_path / "input.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, _logged(counts))
    recover(inp, out)
    uns = ad.read_h5ad(out).uns["vec_counts"]
    assert uns["input_filename"] == "input.h5ad"
    assert uns["input_sha256"] == sha256(inp)
    assert "input_sha256" in json.loads((tmp_path / "recovered.h5ad.json").read_text())


def test_check_only_needs_no_output_path(tmp_path, capsys):
    counts = np.array([[1, 2], [3, 1]], dtype=np.int32)
    inp, report_path = tmp_path / "input.h5ad", tmp_path / "check.json"
    _write(inp, _logged(counts))
    assert main(["recover", str(inp), "--check-only", "--report", str(report_path)]) == 0
    assert json.loads(report_path.read_text())["failing_cell_indices"] == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["check.json", "input.h5ad"]
    assert main(["recover", str(inp)]) == 1
    assert main(["recover", str(inp), str(tmp_path / "x.h5ad"), "--check-only"]) == 1


def test_keep_log1p_stores_the_input_values_once(tmp_path):
    counts = np.array([[1, 3, 0, 5], [0, 2, 3, 0]], dtype=np.int32)
    logged = _logged(counts).tocsc()
    inp, out = tmp_path / "input.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, logged)
    recover(inp, out, keep_log1p=True)
    layer = ad.read_h5ad(out).layers["log1p"]
    np.testing.assert_array_equal(layer.toarray(), logged.toarray())


def test_recovery_does_not_modify_its_input_matrix():
    from vec_counts import _recover_rows

    csr = _logged([[1, 3, 0], [2, 3, 5]]).tocsr()
    csr.data[0] = 0.0  # an explicit stored zero, which recovery must not remove from the caller's matrix
    before = (csr.data.copy(), csr.indices.copy(), csr.indptr.copy())
    _recover_rows(csr, DEFAULT_TOL)
    assert csr.nnz == before[0].size
    np.testing.assert_array_equal(csr.data, before[0])
    np.testing.assert_array_equal(csr.indices, before[1])
    np.testing.assert_array_equal(csr.indptr, before[2])


def test_roundtrip_rejects_mismatched_gene_names(tmp_path):
    counts = np.array([[1, 2], [3, 1]], dtype=np.int32)
    original, recovered = tmp_path / "original.h5ad", tmp_path / "recovered.h5ad"
    other = tmp_path / "other_names.h5ad"
    _write(original, _logged(counts))
    recover(original, recovered)
    _write(other, _logged(counts), names=["x0", "x1"])
    with pytest.raises(ValueError, match="var_names"):
        roundtrip(recovered, other)


def test_legacy_sparse_encoding_is_read(tmp_path):
    counts = np.array([[1, 3, 0], [2, 0, 5]], dtype=np.int32)
    logged = _logged(counts).tocsr()
    inp, out = tmp_path / "legacy.h5ad", tmp_path / "recovered.h5ad"
    _write(inp, np.zeros(counts.shape, dtype=np.float32))
    with h5py.File(inp, "a") as h5:
        del h5["X"]
        group = h5.create_group("X")
        group.attrs["h5sparse_format"] = "csr"
        group.attrs["h5sparse_shape"] = np.array(counts.shape)
        group.create_dataset("data", data=logged.data)
        group.create_dataset("indices", data=logged.indices)
        group.create_dataset("indptr", data=logged.indptr)
    recover(inp, out)
    np.testing.assert_array_equal(ad.read_h5ad(out).X.toarray(), counts)


def test_unrecognised_group_encoding_gives_clear_error(tmp_path):
    inp = tmp_path / "unknown.h5ad"
    _write(inp, np.zeros((2, 3), dtype=np.float32))
    with h5py.File(inp, "a") as h5:
        del h5["X"]
        h5.create_group("X").create_dataset("data", data=np.zeros(1))
    with pytest.raises(ValueError, match="encoding"):
        recover(inp, tmp_path / "out.h5ad")
