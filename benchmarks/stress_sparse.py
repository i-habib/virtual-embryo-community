from __future__ import annotations

import argparse
import json
import resource
import time

import anndata as ad
import numpy as np
from scipy import sparse

from vec_blender.methods import mean_graft, population_mix


def rss_mib() -> float:
    return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0)


def random_csr(rng, rows, cols, density):
    return sparse.random(rows, cols, density=density, format="csr", dtype=np.float32, random_state=rng, data_rvs=lambda n: rng.random(n, dtype=np.float32) * 5.0)


def make_ad(X):
    a = ad.AnnData(X=X)
    a.var_names = [f"g{i}" for i in range(a.n_vars)]
    return a


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cells", type=int, default=10000)
    p.add_argument("--mean-cells", type=int, default=1000)
    p.add_argument("--genes", type=int, default=32285)
    p.add_argument("--density", type=float, default=0.02)
    args = p.parse_args()
    rng = np.random.default_rng(20260930)

    t0=time.perf_counter()
    A=make_ad(random_csr(rng,args.cells,args.genes,args.density)); B=make_ad(random_csr(rng,args.cells,args.genes,args.density))
    mix=population_mix(A,B,alpha=0.5,n_out=args.cells,seed=0).adata
    mix_seconds=time.perf_counter()-t0
    if not sparse.issparse(mix.X): raise AssertionError("population mixture densified sparse expression")

    t1=time.perf_counter()
    M1=make_ad(random_csr(rng,args.mean_cells,args.genes,args.density)); M2=make_ad(random_csr(rng,args.mean_cells,args.genes,args.density))
    graft=mean_graft(M1,M2,clip_min=0.0,chunk_rows=128).adata
    mean_seconds=time.perf_counter()-t1
    if graft.X.dtype != np.float32: raise AssertionError("mean graft output is not float32")

    print(json.dumps({"mixture_cells":args.cells,"mean_graft_cells":args.mean_cells,"genes":args.genes,"input_density":args.density,"mixture_output_sparse":True,"mixture_seconds":mix_seconds,"mean_graft_seconds":mean_seconds,"peak_rss_mib":rss_mib()},indent=2))


if __name__ == "__main__":
    main()
