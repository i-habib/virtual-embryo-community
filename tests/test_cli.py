import hashlib
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
    a.write_h5ad(a_path); b.write_h5ad(b_path)
    return a, b, a_path, b_path


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_mean_graft_writes_reopenable_h5ad_and_manifest(tmp_path):
    a, _, a_path, b_path = _write_pair(tmp_path, [[5,10],[7,14],[9,18]], [[1,2],[4,3],[9,8]])
    out_path = tmp_path / "out.h5ad"
    main(["blend",str(a_path),str(b_path),"--method","mean-graft","-o",str(out_path)])
    reopened=ad.read_h5ad(out_path)
    np.testing.assert_allclose(np.asarray(reopened.X).mean(0),np.asarray(a.X).mean(0),atol=1e-6)
    manifest=json.loads((tmp_path/"out.h5ad.blend.json").read_text())
    assert manifest["method"]=="mean_graft" and manifest["cells"]==3
    assert manifest["input_a_sha256"]==_sha256(a_path); assert manifest["input_b_sha256"]==_sha256(b_path)
    assert manifest["vec_blend_version"]!="unknown"


def test_cli_rejects_negative_mean_graft_without_clip(tmp_path):
    _,_,a_path,b_path=_write_pair(tmp_path,[[0,0],[0,0]],[[0,10],[10,0]])
    out=tmp_path/"negative.h5ad"
    with pytest.raises(ValueError,match="veckit rejects negative"):
        main(["blend",str(a_path),str(b_path),"--method","mean-graft","-o",str(out)])
    assert not out.exists()


def test_cli_rejects_negative_clip_floor(tmp_path):
    _,_,a_path,b_path=_write_pair(tmp_path,[[1],[2]],[[1],[2]])
    with pytest.raises(ValueError,match="clip-min"):
        main(["blend",str(a_path),str(b_path),"--method","mean-graft","--clip-min","-0.1","-o",str(tmp_path/"bad.h5ad")])


def test_cli_clip_makes_negative_mean_graft_writable(tmp_path):
    _,_,a_path,b_path=_write_pair(tmp_path,[[0,0],[0,0]],[[0,10],[10,0]])
    out=tmp_path/"clipped.h5ad"
    main(["blend",str(a_path),str(b_path),"--method","mean-graft","--clip-min","0","-o",str(out)])
    assert float(np.min(np.asarray(ad.read_h5ad(out).X)))>=0.0


def test_final_validator_blocks_negative_mixture_output(tmp_path):
    _,_,a_path,b_path=_write_pair(tmp_path,[[-1,0],[0,1]],[[2,0],[0,2]])
    out=tmp_path/"mix.h5ad"
    with pytest.raises(ValueError,match="negative expression"):
        main(["blend",str(a_path),str(b_path),"--method","mixture","--alpha","1","--n-out","2","-o",str(out)])
    assert not out.exists()


def test_sweep_requires_fixed_count_when_parent_counts_differ(tmp_path):
    _,_,a_path,_=_write_pair(tmp_path,[[1],[2]],[[1],[2]])
    b=ad.AnnData(X=np.asarray([[1],[2],[3]],dtype=np.float32)); b.var_names=["g0"]; b_path=tmp_path/"b3.h5ad"; b.write_h5ad(b_path)
    with pytest.raises(ValueError,match="Pass --n-out"):
        main(["sweep",str(a_path),str(b_path),"--out-dir",str(tmp_path/"sweep")])
