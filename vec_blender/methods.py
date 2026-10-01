from __future__ import annotations

from dataclasses import dataclass

import anndata as ad
import numpy as np
from scipy import sparse
from scipy.optimize import linear_sum_assignment
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors

from .io import (
    build_output,
    dense_rows_cols,
    matrix_mean,
    matrix_variance,
    spatial_coords,
    take_rows,
    validate_pair,
)


@dataclass
class BlendResult:
    adata: ad.AnnData
    report: dict


def _choice(rng: np.random.Generator, n_source: int, n_take: int) -> np.ndarray:
    return rng.choice(n_source, size=n_take, replace=n_take > n_source)


def population_mix(a: ad.AnnData, b: ad.AnnData, *, alpha: float = 0.5, n_out: int | None = None, seed: int = 0) -> BlendResult:
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be in [0, 1]")
    a, b = validate_pair(a, b)
    if n_out is None:
        n_out = int(round(alpha * a.n_obs + (1.0 - alpha) * b.n_obs))
    if n_out <= 0:
        raise ValueError("n_out must be positive")
    n_a = int(round(alpha * n_out))
    n_b = n_out - n_a
    rng = np.random.default_rng(seed)
    ia = _choice(rng, a.n_obs, n_a)
    ib = _choice(rng, b.n_obs, n_b)
    XA = take_rows(a.X, ia)
    XB = take_rows(b.X, ib)
    if sparse.issparse(XA) or sparse.issparse(XB):
        X = sparse.vstack([sparse.csr_matrix(XA), sparse.csr_matrix(XB)], format="csr").astype(np.float32, copy=False)
    else:
        X = np.concatenate([XA, XB], axis=0).astype(np.float32, copy=False)
    ca = spatial_coords(a)
    cb = spatial_coords(b)
    if (ca is None) != (cb is None):
        raise ValueError("Population mixing requires both submissions to either contain spatial_3D or both omit it")
    coords = None if ca is None else np.concatenate([ca[ia], cb[ib]], axis=0)
    out = build_output(X, a, coords=coords, obs_indices=None, obs_prefix="mix")
    out.uns["vec_blender"].update({"method":"population_mix","alpha":float(alpha),"seed":int(seed),"n_from_a":int(n_a),"n_from_b":int(n_b)})
    return BlendResult(out,{"method":"population_mix","alpha":float(alpha),"seed":int(seed),"n_out":int(n_out),"n_from_a":int(n_a),"n_from_b":int(n_b),"sparse_output":bool(sparse.issparse(out.X))})


def mean_graft(mean_donor: ad.AnnData, structure_carrier: ad.AnnData, *, clip_min: float | None = None, chunk_rows: int = 512) -> BlendResult:
    if clip_min is not None and clip_min < 0:
        raise ValueError("clip_min must be >= 0")
    if chunk_rows <= 0:
        raise ValueError("chunk_rows must be positive")
    a, b = validate_pair(mean_donor, structure_carrier)
    mu_a = matrix_mean(a.X)
    mu_b = matrix_mean(b.X)
    delta = (mu_a - mu_b).astype(np.float32, copy=False)
    X = np.empty((b.n_obs, b.n_vars), dtype=np.float32)
    negative_count = 0
    total = int(b.n_obs * b.n_vars)
    for start in range(0, b.n_obs, chunk_rows):
        stop = min(start + chunk_rows, b.n_obs)
        rows = np.arange(start, stop)
        block = take_rows(b.X, rows)
        if sparse.issparse(block):
            block = block.toarray()
        block = np.asarray(block, dtype=np.float32) + delta[None, :]
        negative_count += int(np.count_nonzero(block < 0))
        if clip_min is not None:
            np.maximum(block, np.float32(clip_min), out=block)
        X[start:stop] = block
    coords = spatial_coords(b)
    out = build_output(X,b,coords=coords,obs_indices=np.arange(b.n_obs),obs_prefix="mean_graft")
    stored={"method":"mean_graft","chunk_rows":int(chunk_rows)}
    if clip_min is not None: stored["clip_min"]=float(clip_min)
    out.uns["vec_blender"].update(stored)
    mean_error=float(np.max(np.abs(X.mean(axis=0,dtype=np.float64)-mu_a)))
    return BlendResult(out,{"method":"mean_graft","clip_min":clip_min,"max_abs_mean_error":mean_error,"negative_fraction_before_clipping":float(negative_count/max(total,1)),"structure_cells":int(b.n_obs),"chunk_rows":int(chunk_rows),"output_dtype":"float32"})


def _column_accessor(X):
    if sparse.issparse(X):
        Xc=X.tocsc().astype(np.float32,copy=False)
        return lambda j: Xc.getcol(j).toarray().ravel().astype(np.float32,copy=False)
    A=np.asarray(X,dtype=np.float32)
    return lambda j: A[:,j]


def quantile_graft(marginal_donor: ad.AnnData, rank_carrier: ad.AnnData) -> BlendResult:
    a,b=validate_pair(marginal_donor,rank_carrier)
    source_col=_column_accessor(a.X); carrier_col=_column_accessor(b.X)
    n_src,g=a.shape; n_car=b.n_obs
    X=np.empty((n_car,g),dtype=np.float32)
    for j in range(g):
        s=np.sort(source_col(j),kind="mergesort")
        order=np.argsort(carrier_col(j),kind="mergesort")
        if n_src==n_car:
            mapped=s
        else:
            q=(np.arange(n_car,dtype=np.float32)+0.5)/n_car
            xp=(np.arange(n_src,dtype=np.float32)+0.5)/n_src
            mapped=np.interp(q,xp,s,left=s[0],right=s[-1]).astype(np.float32)
        X[order,j]=mapped
    coords=spatial_coords(b)
    out=build_output(X,b,coords=coords,obs_indices=np.arange(b.n_obs),obs_prefix="quantile_graft")
    out.uns["vec_blender"].update({"method":"quantile_graft"})
    return BlendResult(out,{"method":"quantile_graft","cells":int(b.n_obs),"exact_empirical_marginals":bool(a.n_obs==b.n_obs),"max_sorted_marginal_error":0.0 if a.n_obs==b.n_obs else None,"output_dtype":"float32"})


def _select_match_genes(a,b,max_genes):
    if max_genes<=0: raise ValueError("max_match_genes must be positive")
    g=a.n_vars
    if g<=max_genes: return np.arange(g)
    score=matrix_variance(a.X)+matrix_variance(b.X)
    idx=np.argpartition(score,-max_genes)[-max_genes:]
    return np.sort(idx)


def _embed_for_matching(XA,XB,n_components):
    A0=XA-XA.mean(axis=0,keepdims=True); B0=XB-XB.mean(axis=0,keepdims=True)
    Z=np.vstack([A0,B0]).astype(np.float32,copy=False)
    scale=Z.std(axis=0,dtype=np.float64).astype(np.float32); scale[scale<1e-7]=1.0; Z/=scale[None,:]
    max_components=min(n_components,Z.shape[1],Z.shape[0]-1)
    if max_components<1: raise ValueError("Not enough cells/genes for expression-space matching")
    solver="randomized" if max_components<min(Z.shape) else "auto"
    Z=PCA(n_components=max_components,svd_solver=solver,random_state=0).fit_transform(Z)
    return Z[:len(XA)],Z[len(XA):]


def _hungarian_match(ZA,ZB):
    aa=np.sum(ZA*ZA,axis=1)[:,None]; bb=np.sum(ZB*ZB,axis=1)[None,:]
    cost=np.maximum(aa+bb-2.0*ZA@ZB.T,0.0)
    rows,cols=linear_sum_assignment(cost); order=np.argsort(rows); cols=cols[order]
    return cols.astype(int),np.sqrt(cost[rows[order],cols])


def _greedy_unique_match(ZA,ZB,*,candidate_k=32):
    n=len(ZA); k=min(max(2,candidate_k),n)
    dist,ind=NearestNeighbors(n_neighbors=k).fit(ZB).kneighbors(ZA)
    priority=np.argsort(dist[:,0])[::-1]; used=np.zeros(n,dtype=bool); match=np.full(n,-1,dtype=int); mdist=np.full(n,np.nan,dtype=float)
    for i in priority:
        chosen=-1; chosen_dist=np.inf
        for d,j in zip(dist[i],ind[i]):
            if not used[j]: chosen=int(j); chosen_dist=float(d); break
        if chosen<0:
            remaining=np.flatnonzero(~used)
            if len(remaining)==0: raise RuntimeError("greedy matcher exhausted all geometry slots")
            delta=ZB[remaining]-ZA[i]; dd=np.einsum("ij,ij->i",delta,delta); pos=int(np.argmin(dd)); chosen=int(remaining[pos]); chosen_dist=float(np.sqrt(dd[pos]))
        match[i]=chosen; mdist[i]=chosen_dist; used[chosen]=True
    return match,mdist


def spatial_transplant(expression_donor: ad.AnnData, geometry_carrier: ad.AnnData, *, n_out: int | None=None, seed:int=0, n_components:int=24, assignment:str="auto", exact_limit:int=2500, max_match_genes:int=2048) -> BlendResult:
    a,b=validate_pair(expression_donor,geometry_carrier); Cb=spatial_coords(b)
    if Cb is None: raise ValueError("geometry carrier B must contain obsm['spatial_3D']")
    if n_out is None: n_out=min(a.n_obs,b.n_obs)
    if n_out<=1 or n_out>min(a.n_obs,b.n_obs): raise ValueError("n_out must be >1 and cannot exceed the smaller submission cell count")
    rng=np.random.default_rng(seed)
    ia=np.arange(a.n_obs) if n_out==a.n_obs else np.sort(rng.choice(a.n_obs,n_out,replace=False))
    ib=np.arange(b.n_obs) if n_out==b.n_obs else np.sort(rng.choice(b.n_obs,n_out,replace=False))
    match_genes=_select_match_genes(a,b,max_match_genes)
    XAm=dense_rows_cols(a.X,ia,match_genes); XBm=dense_rows_cols(b.X,ib,match_genes)
    ZA,ZB=_embed_for_matching(XAm,XBm,n_components=n_components)
    if assignment=="auto": assignment_used="hungarian" if n_out<=exact_limit else "greedy"
    elif assignment in {"hungarian","greedy"}: assignment_used=assignment
    else: raise ValueError("assignment must be 'auto', 'hungarian', or 'greedy'")
    match,distances=_hungarian_match(ZA,ZB) if assignment_used=="hungarian" else _greedy_unique_match(ZA,ZB)
    matched_b=ib[match]; coords=Cb[matched_b]; XA_out=take_rows(a.X,ia)
    out=build_output(XA_out,a,coords=coords,obs_indices=ia,obs_prefix="spatial_transplant")
    out.uns["vec_blender"].update({"method":"spatial_transplant","seed":int(seed),"assignment":assignment_used,"n_components":int(min(n_components,ZA.shape[1])),"match_genes":int(len(match_genes)),"expression_source":"A","coordinate_source":"B","obs_source":"A"})
    report={"method":"spatial_transplant","seed":int(seed),"n_out":int(n_out),"assignment":assignment_used,"embedding_components":int(ZA.shape[1]),"match_genes":int(len(match_genes)),"max_match_genes":int(max_match_genes),"mean_match_distance":float(np.mean(distances)),"p95_match_distance":float(np.quantile(distances,0.95)),"max_match_distance":float(np.max(distances)),"subsampled_a":bool(n_out!=a.n_obs),"subsampled_b":bool(n_out!=b.n_obs),"obs_source":"A","coordinate_source":"B","obs_location_metadata_may_be_stale":bool(len(a.obs.columns)>0)}
    return BlendResult(out,report)
