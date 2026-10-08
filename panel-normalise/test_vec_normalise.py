import inspect
import io
import json

import anndata as ad
import numpy as np
import pandas as pd
import pytest
from scipy import sparse

import vec_normalise
from vec_normalise import main, normalize, resolve_names, verify_release


@pytest.fixture
def mgi(tmp_path):
    (tmp_path / "MRK_List2.rpt").write_text(
        "MGI Accession ID\tMarker Symbol\tStatus\tMarker Type\tMarker Synonyms (pipe-separated)\n"
        "MGI:1\tAlpha\tO\tGene\toldalpha|shared\n"
        "MGI:2\tBeta\tO\tGene\toldbeta|shared|CurrentOther|oldbeta2\n"
        "MGI:3\tGamma\tO\tGene\toldgamma\n"
        "MGI:4\tDelta\tO\tGene\t\n"
        "MGI:5\tCurrentOther\tO\tGene\toldoutside\n"
        "MGI:6\tDecoy\tO\tQTL\toldbeta\n"
        "MGI:7\tt\tO\tGene\t\n"
        "MGI:8\tT\tO\tGene\t\n"
        "MGI:9\tEpsilon\tO\tGene\tQTLname\n"
        "MGI:10\tQTLname\tO\tQTL\t\n"
    )
    # MRK_ENSEMBL.rpt has no header. Column 2 is a symbol that may differ from the
    # current symbol, so the join must use the MGI accession in column 1.
    (tmp_path / "MRK_ENSEMBL.rpt").write_text(
        "MGI:1\tOldAlphaName\tname\t0\t1\tENSMUSG00000000001\tENSMUST00000000001\n"
        "MGI:2\tBeta\tname\t0\t1\tENSMUSG00000000002\tENSMUST00000000002\n"
        "MGI:3\tGamma\tname\t0\t1\tENSMUSG00000000003\tENSMUST00000000003\n"
    )
    return tmp_path


def _write_counts(path, X, names):
    ad.AnnData(X=sparse.csr_matrix(X), var=pd.DataFrame(index=pd.Index(names)),
               obs=pd.DataFrame(index=[f"cell{i}" for i in range(X.shape[0])])).write_h5ad(path)


def test_alias_rescue_ensembl_version_and_ambiguous_refusal(mgi):
    rows, missing = resolve_names(
        ["Alpha", "ALPHA", "oldbeta", "ENSMUSG00000000003.7", "shared"],
        ["Alpha", "Beta", "Gamma"], mgi,
    )
    assert [r["target"] for r in rows] == ["Alpha", "", "Beta", "Gamma", ""]
    assert [r["class"] for r in rows] == ["exact", "conflict", "rescued", "rescued", "ambiguous"]
    assert missing == []


def test_synonym_refused_when_current_symbol_exactly_present(mgi):
    rows, _ = resolve_names(["Alpha", "oldalpha"], ["Alpha"], mgi)
    assert rows[1]["class"] == "conflict"
    assert rows[1]["target"] == ""


def test_current_symbol_outside_panel_does_not_fall_through_to_synonym(mgi):
    rows, _ = resolve_names(["CurrentOther"], ["Beta"], mgi)
    assert rows[0]["class"] == "unmatched"
    assert rows[0]["target"] == ""


def test_duplicate_columns_summed_as_raw_counts_before_log(mgi, tmp_path):
    # oldbeta (10) and oldbeta2 (30) both map to Beta, so Beta is 40 raw counts.
    # Summing log values instead would not give the same result.
    panel = tmp_path / "panel.txt"
    panel.write_text("Alpha\nBeta\nGamma\n")
    inp, out = tmp_path / "in.h5ad", tmp_path / "out.h5ad"
    _write_counts(inp, np.array([[10, 10, 30, 10]], dtype=np.int32), ["Alpha", "oldbeta", "oldbeta2", "Gamma"])
    normalize(inp, panel, out, mgi_dir=mgi)
    data = ad.read_h5ad(out)
    expected = np.log1p(40 / 60 * 10000)
    assert data.X[0, 1] == pytest.approx(expected, abs=1e-4)
    assert data.uns["vec_normalise"]["duplicate_targets_summed"] == {"Beta": 2}


def test_case_only_match_refused_when_casefold_key_has_two_symbols(mgi):
    rows, _ = resolve_names(["t", "gamma"], ["T", "Gamma"], mgi)
    assert rows[0]["class"] == "ambiguous"
    assert rows[0]["target"] == ""
    assert rows[1]["class"] == "rescued"
    assert rows[1]["target"] == "Gamma"


def test_rescue_refused_for_every_route_when_target_is_exact(mgi):
    # Alpha and Beta are exact input columns, so case, synonym and Ensembl rescues into them conflict.
    rows, missing = resolve_names(
        ["Alpha", "ALPHA", "oldalpha", "ENSMUSG00000000001", "Beta", "ENSMUSG00000000002"],
        ["Alpha", "Beta"], mgi,
    )
    assert [r["class"] for r in rows] == ["exact", "conflict", "conflict", "conflict", "exact", "conflict"]
    assert all(r["target"] == "" for r in rows[1:4] + rows[5:])
    assert missing == []


def test_non_gene_symbol_is_not_treated_as_synonym(mgi):
    # QTLname is a current symbol of a QTL record, and Epsilon lists it as a synonym.
    # Protected symbols of other marker types must not be rescued into a gene.
    rows, missing = resolve_names(["QTLname"], ["Epsilon"], mgi)
    assert rows[0]["class"] == "unmatched"
    assert rows[0]["target"] == ""
    assert missing == ["Epsilon"]


def test_ensembl_joined_by_mgi_accession_and_retired_ids_unmatched(mgi):
    rows, _ = resolve_names(["ENSMUSG00000000001.4", "ENSMUSG00000099999"], ["Alpha"], mgi)
    assert rows[0]["target"] == "Alpha"
    assert rows[0]["class"] == "rescued"
    assert rows[1]["class"] == "unmatched"


def _write_log_cp10k(path, counts, names):
    counts = np.asarray(counts, dtype=np.float64)
    X = np.log1p(counts / counts.sum(axis=1, keepdims=True) * 10000).astype(np.float32)
    ad.AnnData(X=X, var=pd.DataFrame(index=pd.Index(names)),
               obs=pd.DataFrame(index=[f"c{i}" for i in range(X.shape[0])])).write_h5ad(path)


def test_allow_noninteger_refuses_log_cp10k_but_accepts_fractional_counts(mgi, tmp_path):
    panel = tmp_path / "panel.txt"
    panel.write_text("Alpha\nBeta\n")
    logged, out = tmp_path / "logged.h5ad", tmp_path / "out.h5ad"
    _write_log_cp10k(logged, [[1, 3], [4, 2]], ["Alpha", "Beta"])
    with pytest.raises(ValueError, match="looks log-transformed"):
        normalize(logged, panel, out, allow_noninteger=True, mgi_dir=mgi)
    fractional = tmp_path / "fractional.h5ad"
    _write_counts(fractional, np.array([[0.5, 2.25], [3.1, 0.2]]), ["Alpha", "Beta"])
    normalize(fractional, panel, out, allow_noninteger=True, mgi_dir=mgi)
    assert np.isfinite(ad.read_h5ad(out).X.toarray()).all()


def test_filled_zero_column_and_mapping_table_stored_in_uns(mgi, tmp_path):
    panel = tmp_path / "panel.txt"
    panel.write_text("Alpha\nDelta\n")
    inp, out = tmp_path / "in.h5ad", tmp_path / "out.h5ad"
    _write_counts(inp, np.array([[2]], dtype=np.int32), ["Alpha"])
    normalize(inp, panel, out, fill_missing=True, mgi_dir=mgi)
    data = ad.read_h5ad(out)
    assert data.var["filled_zero"].tolist() == [False, True]
    assert data.var["filled_zero"].dtype == bool
    mapping = data.uns["vec_normalise_mapping"]
    assert isinstance(mapping, pd.DataFrame)
    missing_rows = mapping[mapping["class"] == "missing"]
    assert missing_rows["target"].tolist() == ["Delta"]


def test_mgi_download_recorded_once_and_not_repeated(tmp_path, monkeypatch, mgi):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    calls = []

    def fake_download(url, target, timeout=vec_normalise.MGI_TIMEOUT_SECONDS):
        calls.append(url)
        target.write_bytes((mgi / target.name).read_bytes())

    monkeypatch.setattr(vec_normalise, "_download", fake_download)
    resolve_names(["Alpha"], ["Alpha"], None)
    cache = tmp_path / "cache" / "vec-normalise" / "mgi"
    first = (cache / "MRK_List2.rpt.metadata.json").read_text()
    recorded = json.loads(first)
    assert recorded["url"] == vec_normalise.MGI_URLS["MRK_List2.rpt"]
    assert recorded["downloaded"] and len(recorded["sha256"]) == 64
    assert recorded["header"].startswith("MGI Accession ID")
    resolve_names(["Alpha"], ["Alpha"], None)
    assert len(calls) == 2
    assert (cache / "MRK_List2.rpt.metadata.json").read_text() == first
    assert not list(cache.glob("*.part"))


def test_download_uses_timeout_and_leaves_no_partial_file(tmp_path, monkeypatch):
    seen = {}

    class Dropped:
        def __init__(self):
            self.reads = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, size=-1):
            self.reads += 1
            if self.reads == 1:
                return b"MGI partial"
            raise ConnectionError("connection dropped")

    def fake_urlopen(url, timeout=None):
        seen["timeout"] = timeout
        return Dropped()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    target = tmp_path / "MRK_List2.rpt"
    with pytest.raises(ConnectionError):
        vec_normalise._download("https://example.invalid/x", target)
    assert seen["timeout"] == vec_normalise.MGI_TIMEOUT_SECONDS
    assert not target.exists()
    assert not list(tmp_path.glob("*.part"))

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: io.BytesIO(b"ok\n"))
    vec_normalise._download("https://example.invalid/x", target)
    assert target.read_bytes() == b"ok\n"
    assert not list(tmp_path.glob("*.part"))


def test_dense_and_sparse_inputs_match_across_row_blocks(mgi, tmp_path, monkeypatch):
    panel = tmp_path / "panel.txt"
    panel.write_text("Alpha\nBeta\nGamma\n")
    dense_counts = np.array([[3, 0, 7, 1], [0, 5, 2, 9], [4, 4, 0, 0]], dtype=np.int32)
    names = ["Alpha", "oldbeta", "oldbeta2", "Gamma"]
    dense_in, sparse_in = tmp_path / "dense.h5ad", tmp_path / "sparse.h5ad"
    ad.AnnData(X=dense_counts, var=pd.DataFrame(index=pd.Index(names)),
               obs=pd.DataFrame(index=["a", "b", "c"])).write_h5ad(dense_in)
    _write_counts(sparse_in, dense_counts, names)
    monkeypatch.setattr(vec_normalise, "BLOCK_ROWS", 1)
    normalize(dense_in, panel, tmp_path / "d1.h5ad", mgi_dir=mgi)
    normalize(sparse_in, panel, tmp_path / "s1.h5ad", mgi_dir=mgi)
    monkeypatch.setattr(vec_normalise, "BLOCK_ROWS", 2000)
    normalize(sparse_in, panel, tmp_path / "s2.h5ad", mgi_dir=mgi)
    d1, s1, s2 = (ad.read_h5ad(tmp_path / f) for f in ("d1.h5ad", "s1.h5ad", "s2.h5ad"))
    assert sparse.isspmatrix_csr(s1.X) and s1.X.dtype == np.float32
    assert np.allclose(d1.X.toarray(), s1.X.toarray(), atol=1e-6)
    assert np.allclose(s1.X.toarray(), s2.X.toarray(), atol=1e-6)


def test_dead_parameters_and_inspect_norm_removed(capsys):
    assert "scope" not in inspect.signature(normalize).parameters
    assert "report_only" not in inspect.signature(verify_release).parameters
    assert not hasattr(vec_normalise, "inspect_norm")
    with pytest.raises(SystemExit):
        main(["inspect-norm", "missing.h5ad"])


def test_panel_normalisation_ignores_unmatched_columns(mgi, tmp_path):
    panel = tmp_path / "panel.txt"
    panel.write_text("Alpha\nBeta\nGamma\nDelta\n")
    inp, out = tmp_path / "in.h5ad", tmp_path / "panel.h5ad"
    _write_counts(inp, np.array([[10, 10, 10, 10, 60], [5, 5, 5, 5, 80]], dtype=np.int32),
                  ["Alpha", "Beta", "Beta", "ENSMUSG00000000003.4", "Other"])
    normalize(inp, panel, out, fill_missing=True, mgi_dir=mgi)
    panel_data = ad.read_h5ad(out)
    assert list(panel_data.var_names) == ["Alpha", "Beta", "Gamma", "Delta"]
    assert sparse.isspmatrix_csr(panel_data.X)
    assert np.allclose(np.expm1(panel_data.X.toarray()).sum(axis=1), 10000, atol=1e-3)
    assert np.allclose(panel_data.X[:, 1].toarray().ravel(), np.log1p(np.array([20, 10]) / np.array([40, 20]) * 10000), atol=1e-6)
    assert panel_data.uns["vec_normalise"]["duplicate_targets_summed"] == {"Beta": 2}
    assert list(panel_data.uns["vec_normalise"]["filled_missing"]) == ["Delta"]


def test_missing_rejected_unless_fill_requested(mgi, tmp_path):
    panel = tmp_path / "panel.txt"
    panel.write_text("Alpha\nDelta\n")
    inp, out = tmp_path / "in.h5ad", tmp_path / "out.h5ad"
    _write_counts(inp, np.array([[2]], dtype=np.int32), ["Alpha"])
    with pytest.raises(ValueError, match="panel genes are missing"):
        normalize(inp, panel, out, mgi_dir=mgi)
    normalize(inp, panel, out, fill_missing=True, mgi_dir=mgi)
    assert list(ad.read_h5ad(out).uns["vec_normalise"]["filled_missing"]) == ["Delta"]


def test_log_input_refusal(mgi, tmp_path):
    panel = tmp_path / "panel.txt"
    panel.write_text("Alpha\n")
    inp, out = tmp_path / "logged.h5ad", tmp_path / "out.h5ad"
    _write_counts(inp, np.array([[1.2], [2.7]], dtype=np.float32), ["Alpha"])
    with pytest.raises(ValueError, match="does not look like raw counts"):
        normalize(inp, panel, out, mgi_dir=mgi)


def test_verify_release_like_file(mgi, tmp_path):
    counts = sparse.csr_matrix(np.array([[1, 2], [3, 4]], dtype=np.int32))
    X = counts.multiply((10000 / np.asarray(counts.sum(axis=1)).ravel())[:, None]).tocsr()
    X.data = np.log1p(X.data)
    path = tmp_path / "release.h5ad"
    data = ad.AnnData(X=X.astype(np.float32), var=pd.DataFrame(index=["A", "B"]),
                      obs=pd.DataFrame(index=["c0", "c1"]))
    data.layers["counts"] = counts
    data.write_h5ad(path)
    report = verify_release(path)
    assert report["scope"] == "panel"
    assert report["delta_max"] < 1e-6


def test_verify_without_counts_reports_row_sums_and_panel_scope(tmp_path):
    panel = tmp_path / "panel.txt"
    panel.write_text("A\nB\n")
    X = np.log1p(np.array([[5000.0, 5000.0], [2500.0, 7500.0]], dtype=np.float32))
    path = tmp_path / "normalized.h5ad"
    ad.AnnData(X=X, var=pd.DataFrame(index=["A", "B"]),
               obs=pd.DataFrame(index=["c0", "c1"])).write_h5ad(path)
    report = verify_release(path, panel)
    assert report["counts_layer"] is False
    assert report["panel_order_matches"] is True
    assert report["implied_scope"].startswith("panel")
    assert report["expm1_row_sum_quantiles"][1] == pytest.approx(10000, abs=5e-3)
