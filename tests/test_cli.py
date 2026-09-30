import json

import anndata as ad
import numpy as np
import pytest

from vec_blender.cli import main


def _write_pair(tmp_path, A, B):
    a = ad.AnnData(X=np.asarray(A, dtype=np.float32))
    b = ad.AnnData(X=np.asarray(B, dtype=np.float32))
    a.var_names = [f"g{i}" for i in range(a.n_vars)]
    b.var_names = list(a.var_names)
    a_path = tmp_path / "a.h5ad"
    b_path = tmp_path / "b.h5ad"
    a.write_h5ad(a_path)
    b.write_h5ad(b_path)
    return a, b, a_path, b_path


def test_cli_mean_graft_writes_reopenable_h5ad_and_manifest(tmp_path):
    a, b, a_path, b_path = _write_pair(
        tmp_path,
        [[5, 10], [7, 14], [9, 18]],
        [[1, 2], [4, 3], [9, 8]],
    )
    out_path = tmp_path / "out.h5ad"

    main([
        "blend", str(a_path), str(b_path),
        "--method", "mean-graft", "-o", str(out_path)
    ])

    reopened = ad.read_h5ad(out_path)
    np.testing.assert_allclose(
        np.asarray(reopened.X).mean(0), np.asarray(a.X).mean(0), atol=1e-6
    )
    assert reopened.uns["vec_blender"]["method"] == "mean_graft"

    manifest = json.loads((tmp_path / "out.h5ad.blend.json").read_text())
    assert manifest["method"] == "mean_graft"
    assert manifest["cells"] == 3


def test_cli_rejects_negative_mean_graft_without_clip(tmp_path):
    _, _, a_path, b_path = _write_pair(
        tmp_path,
        [[0, 0], [0, 0]],
        [[0, 10], [10, 0]],
    )
    out_path = tmp_path / "negative.h5ad"

    with pytest.raises(ValueError, match="veckit rejects negative"):
        main([
            "blend", str(a_path), str(b_path),
            "--method", "mean-graft", "-o", str(out_path)
        ])
    assert not out_path.exists()


def test_cli_clip_makes_negative_mean_graft_writable(tmp_path):
    _, _, a_path, b_path = _write_pair(
        tmp_path,
        [[0, 0], [0, 0]],
        [[0, 10], [10, 0]],
    )
    out_path = tmp_path / "clipped.h5ad"

    main([
        "blend", str(a_path), str(b_path),
        "--method", "mean-graft", "--clip-min", "0", "-o", str(out_path)
    ])

    reopened = ad.read_h5ad(out_path)
    assert float(np.min(np.asarray(reopened.X))) >= 0.0
