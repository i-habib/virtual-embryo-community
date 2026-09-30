import json

import anndata as ad
import numpy as np

from vec_blender.cli import main


def test_cli_mean_graft_writes_reopenable_h5ad_and_manifest(tmp_path):
    a = ad.AnnData(X=np.array([[5, 10], [7, 14], [9, 18]], dtype=np.float32))
    b = ad.AnnData(X=np.array([[1, 2], [4, 3], [9, 8]], dtype=np.float32))
    a.var_names = ["g1", "g2"]
    b.var_names = ["g1", "g2"]
    a_path = tmp_path / "a.h5ad"
    b_path = tmp_path / "b.h5ad"
    out_path = tmp_path / "out.h5ad"
    a.write_h5ad(a_path)
    b.write_h5ad(b_path)

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
