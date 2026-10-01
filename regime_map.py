from __future__ import annotations

import argparse, json, tempfile
from pathlib import Path

import anndata as ad
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from run_lab import VECKIT_COMMIT, dense, download_public_samples, make_like, positive_offset, save_and_score
from vec_blender.methods import mean_graft, population_mix, quantile_graft, spatial_transplant

T1_PRIMARY={"de_score":"high","de_direction":"high","mmd_u":"low","variogram":"low"}
T2_PRIMARY={"de_score":"high","de_direction":"high","mmd_u":"low","variogram":"low","d2_shape":"low","sliced_wasserstein":"low","occupancy_dice":"high","neighborhood_mmd":"low"}
LEVELS=(0.0,0.1,0.3,0.6)


def align_source(source,target):
    genes=list(map(str,target.var_names))
    if set(map(str,source.var_names))!=set(genes): raise ValueError("source and target do not share the same gene set")
    return source[:,genes]


def gene_shuffle(X,seed):
    rng=np.random.default_rng(seed); out=np.empty_like(X)
    for j in range(X.shape[1]): out[:,j]=X[rng.permutation(X.shape[0]),j]
    return out


def partial_rank_corruption(X,fraction,seed):
    if fraction<=0: return X.copy()
    rng=np.random.default_rng(seed); out=X.copy(); n=X.shape[0]; k=max(2,min(n,int(round(fraction*n))))
    for j in range(X.shape[1]):
        idx=rng.choice(n,size=k,replace=False); out[idx,j]=X[rng.permutation(idx),j]
    return out


def better_than_both(a,b,blend,directions):
    wins=losses=0
    for metric,direction in directions.items():
        av,bv,cv=map(float,(a[metric],b[metric],blend[metric])); tol=1e-8*max(1.0,abs(av),abs(bv),abs(cv))
        if direction=="high": wins+=int(cv>max(av,bv)+tol); losses+=int(cv<min(av,bv)-tol)
        else: wins+=int(cv<min(av,bv)-tol); losses+=int(cv>max(av,bv)+tol)
    return wins,losses


def score_pred(pred,*,name,task,work,target,reference=None,wt=None):
    return save_and_score(pred,name=name,task=task,work=work,target=target,reference=reference,wt=wt)


def baseline_rows(samples,work):
    rows=[]
    t=ad.read_h5ad(samples["sample_9.5.h5ad"]); r=align_source(ad.read_h5ad(samples["sample_8.5.h5ad"]),t)
    p=make_like(t,dense(r),prefix="copy_last_t1"); s=score_pred(p,name="copy_last_T1",task="T1",work=work,target=samples["sample_9.5.h5ad"],reference=samples["sample_8.5.h5ad"]); rows.append({"task":"T1","baseline":"copy_last",**s})
    t=ad.read_h5ad(samples["sample_heart_9.5.h5ad"]); r=align_source(ad.read_h5ad(samples["sample_heart_9.25.h5ad"]),t)
    p=make_like(t,dense(r),coords=np.asarray(r.obsm["spatial_3D"])[:,:3],prefix="copy_last_t2"); s=score_pred(p,name="copy_last_T2",task="T2",work=work,target=samples["sample_heart_9.5.h5ad"],reference=samples["sample_heart_9.25.h5ad"]); rows.append({"task":"T2-heart","baseline":"copy_last",**s})
    t=ad.read_h5ad(samples["sample_mab21l2_ko.h5ad"]); wt=align_source(ad.read_h5ad(samples["sample_wt.h5ad"]),t); c=np.asarray(wt.obsm["spatial_3D"])[:,:3] if "spatial_3D" in wt.obsm else None
    p=make_like(t,dense(wt),coords=c,prefix="wt_identity"); s=score_pred(p,name="wt_identity_T3",task="T3",work=work,target=samples["sample_mab21l2_ko.h5ad"],wt=samples["sample_wt.h5ad"]); rows.append({"task":"T3","baseline":"wt_identity",**s})
    return rows


def t1_mean_regime(samples,work):
    tp,rp=samples["sample_9.5.h5ad"],samples["sample_8.5.h5ad"]; t=ad.read_h5ad(tp); X=dense(t); mu=X.mean(0); R=X-mu; off=positive_offset(X); sh=gene_shuffle(X,1101)
    As={m:make_like(t,mu[None,:]+0.25*R+m*off[None,:],prefix=f"mean_A_{m}") for m in LEVELS}
    Bs={r:make_like(t,(1-r)*X+r*sh+1.5*off[None,:],prefix=f"mean_B_{r}") for r in LEVELS}
    sa={m:score_pred(As[m],name=f"mean_A_{m}",task="T1",work=work,target=tp,reference=rp) for m in LEVELS}; sb={r:score_pred(Bs[r],name=f"mean_B_{r}",task="T1",work=work,target=tp,reference=rp) for r in LEVELS}
    rows=[]
    for m in LEVELS:
        for r in LEVELS:
            blend=mean_graft(As[m],Bs[r],clip_min=0).adata; sc=score_pred(blend,name=f"mean_blend_m{m}_r{r}",task="T1",work=work,target=tp,reference=rp); w,l=better_than_both(sa[m],sb[r],sc,T1_PRIMARY)
            rows.append({"mean_error_level":m,"residual_error_level":r,"primary_wins_vs_both":w,"primary_losses_vs_both":l,"primary_win_fraction":w/4,"blend_rmse_to_target":float(np.sqrt(np.mean((dense(blend)-X)**2))),**{f"blend_{k}":sc[k] for k in T1_PRIMARY},**{f"A_{k}":sa[m][k] for k in T1_PRIMARY},**{f"B_{k}":sb[r][k] for k in T1_PRIMARY}})
    return rows


def t1_quantile_regime(samples,work):
    tp,rp=samples["sample_9.5.h5ad"],samples["sample_8.5.h5ad"]; t=ad.read_h5ad(tp); X=dense(t); off=positive_offset(X); scrambled=gene_shuffle(X,2201); g=X.shape[1]; slope=0.2+0.8*(np.arange(g)+1)/g; bad_scale=0.65+0.7*(np.arange(g)+1)/g
    As={m:make_like(t,scrambled*(1+m*slope[None,:])+m*0.4*off[None,:],prefix=f"quant_A_{m}") for m in LEVELS}
    Bs={r:make_like(t,partial_rank_corruption(X,r,2300+int(r*1000))*bad_scale[None,:]+0.8*off[None,:],prefix=f"quant_B_{r}") for r in LEVELS}
    sa={m:score_pred(As[m],name=f"quant_A_{m}",task="T1",work=work,target=tp,reference=rp) for m in LEVELS}; sb={r:score_pred(Bs[r],name=f"quant_B_{r}",task="T1",work=work,target=tp,reference=rp) for r in LEVELS}
    rows=[]
    for m in LEVELS:
        for r in LEVELS:
            blend=quantile_graft(As[m],Bs[r]).adata; sc=score_pred(blend,name=f"quant_blend_m{m}_r{r}",task="T1",work=work,target=tp,reference=rp); w,l=better_than_both(sa[m],sb[r],sc,T1_PRIMARY)
            rows.append({"marginal_error_level":m,"rank_corruption_fraction":r,"primary_wins_vs_both":w,"primary_losses_vs_both":l,"primary_win_fraction":w/4,"blend_rmse_to_target":float(np.sqrt(np.mean((dense(blend)-X)**2))),**{f"blend_{k}":sc[k] for k in T1_PRIMARY},**{f"A_{k}":sa[m][k] for k in T1_PRIMARY},**{f"B_{k}":sb[r][k] for k in T1_PRIMARY}})
    return rows


def t2_spatial_regime(samples,work):
    tp,rp=samples["sample_heart_9.5.h5ad"],samples["sample_heart_9.25.h5ad"]; t=ad.read_h5ad(tp); X=dense(t); C=np.asarray(t.obsm["spatial_3D"],dtype=float)[:,:3]; sh=gene_shuffle(X,3301); rng=np.random.default_rng(3302); cperm=rng.permutation(len(X)); rperm=rng.permutation(len(X)); std=np.std(X,axis=0); shift=0.35+0.55*std
    As={e:make_like(t,(1-e)*X+e*sh,coords=C[cperm],prefix=f"spatial_A_{e}") for e in LEVELS}; Bs={}
    for n in LEVELS:
        nr=np.random.default_rng(3400+int(n*1000)); noise=nr.normal(scale=n*(0.05+std),size=X.shape); XB=np.maximum(X+shift[None,:]+noise,0)[rperm]; Bs[n]=make_like(t,XB,coords=C[rperm],prefix=f"spatial_B_{n}")
    sa={e:score_pred(As[e],name=f"spatial_A_{e}",task="T2",work=work,target=tp,reference=rp) for e in LEVELS}; sb={n:score_pred(Bs[n],name=f"spatial_B_{n}",task="T2",work=work,target=tp,reference=rp) for n in LEVELS}
    rows=[]
    for e in LEVELS:
        for n in LEVELS:
            blend=spatial_transplant(As[e],Bs[n],assignment="hungarian",n_components=24).adata; sc=score_pred(blend,name=f"spatial_blend_e{e}_n{n}",task="T2",work=work,target=tp,reference=rp); w,l=better_than_both(sa[e],sb[n],sc,T2_PRIMARY); err=np.asarray(blend.obsm["spatial_3D"],dtype=float)-C
            rows.append({"expression_corruption":e,"matching_noise":n,"primary_wins_vs_both":w,"primary_losses_vs_both":l,"primary_win_fraction":w/8,"coordinate_rmse":float(np.sqrt(np.mean(err**2))),**{f"blend_{k}":sc[k] for k in T2_PRIMARY},**{f"A_{k}":sa[e][k] for k in T2_PRIMARY},**{f"B_{k}":sb[n][k] for k in T2_PRIMARY}})
    assign=[]; e=0.1
    for n in LEVELS:
        for method in ("hungarian","greedy"):
            res=spatial_transplant(As[e],Bs[n],assignment=method,n_components=24); sc=score_pred(res.adata,name=f"assign_{method}_n{n}",task="T2",work=work,target=tp,reference=rp); err=np.asarray(res.adata.obsm["spatial_3D"],dtype=float)-C
            assign.append({"matching_noise":n,"assignment":method,"coordinate_rmse":float(np.sqrt(np.mean(err**2))),"mean_match_distance":res.report["mean_match_distance"],**{k:sc[k] for k in T2_PRIMARY}})
    return rows,assign


def mixture_regime(samples,work):
    tp,rp=samples["sample_9.5.h5ad"],samples["sample_8.5.h5ad"]; t=ad.read_h5ad(tp); X=dense(t); mu=X.mean(0); R=X-mu; off=positive_offset(X); sh=gene_shuffle(X,4401); rows=[]
    for sev in (0.25,0.5,0.75):
        A=make_like(t,mu[None,:]+(1-sev)*R+0.1*off[None,:],prefix=f"mix_A_{sev}"); B=make_like(t,(1-0.15*sev)*X+0.15*sev*sh+(1.4*sev)*off[None,:],prefix=f"mix_B_{sev}"); sa=score_pred(A,name=f"mix_A_{sev}",task="T1",work=work,target=tp,reference=rp); sb=score_pred(B,name=f"mix_B_{sev}",task="T1",work=work,target=tp,reference=rp)
        for alpha in (0.25,0.5,0.75):
            blend=population_mix(A,B,alpha=alpha,n_out=t.n_obs,seed=17).adata; sc=score_pred(blend,name=f"mix_s{sev}_a{alpha}",task="T1",work=work,target=tp,reference=rp); w,l=better_than_both(sa,sb,sc,T1_PRIMARY)
            rows.append({"complementarity_severity":sev,"alpha":alpha,"primary_wins_vs_both":w,"primary_losses_vs_both":l,"primary_win_fraction":w/4,**{f"blend_{k}":sc[k] for k in T1_PRIMARY},**{f"A_{k}":sa[k] for k in T1_PRIMARY},**{f"B_{k}":sb[k] for k in T1_PRIMARY}})
    return rows


def heatmap(df,row,col,title,out):
    p=df.pivot(index=row,columns=col,values="primary_win_fraction").sort_index().sort_index(axis=1); fig,ax=plt.subplots(figsize=(6,4.5)); im=ax.imshow(p.values,vmin=0,vmax=1,aspect="auto"); ax.set_xticks(range(len(p.columns)),[str(x) for x in p.columns]); ax.set_yticks(range(len(p.index)),[str(x) for x in p.index]); ax.set_xlabel(col.replace("_"," ")); ax.set_ylabel(row.replace("_"," ")); ax.set_title(title)
    for i in range(p.shape[0]):
        for j in range(p.shape[1]): ax.text(j,i,f"{p.iloc[i,j]:.2f}",ha="center",va="center")
    fig.colorbar(im,ax=ax,label="fraction of primary metrics beating both parents"); fig.tight_layout(); fig.savefig(out,dpi=160); plt.close(fig)


def summarize_grid(df,cols):
    exact=np.ones(len(df),dtype=bool)
    for c in cols: exact &= np.asarray(df[c])==0
    d=df.loc[~exact]
    return {"imperfect_grid_points":int(len(d)),"points_with_any_primary_win":int((d.primary_wins_vs_both>0).sum()),"points_with_half_or_more_primary_wins":int((d.primary_win_fraction>=0.5).sum()),"max_primary_wins":int(d.primary_wins_vs_both.max())}


def write_outputs(out_dir,baselines,mean_rows,quant_rows,spatial_rows,assign_rows,mix_rows):
    out_dir.mkdir(parents=True,exist_ok=True); frames={"official_floor_baselines":pd.DataFrame(baselines),"mean_regime":pd.DataFrame(mean_rows),"quantile_regime":pd.DataFrame(quant_rows),"spatial_regime":pd.DataFrame(spatial_rows),"spatial_assignment":pd.DataFrame(assign_rows),"mixture_regime":pd.DataFrame(mix_rows)}
    for n,d in frames.items(): d.to_csv(out_dir/f"{n}.csv",index=False)
    heatmap(frames["mean_regime"],"mean_error_level","residual_error_level","Mean graft: imperfect complementarity",out_dir/"mean_regime.png"); heatmap(frames["quantile_regime"],"marginal_error_level","rank_corruption_fraction","Quantile graft: imperfect complementarity",out_dir/"quantile_regime.png"); heatmap(frames["spatial_regime"],"expression_corruption","matching_noise","Spatial transplant: imperfect complementarity",out_dir/"spatial_regime.png")
    summary={"mean_graft":summarize_grid(frames["mean_regime"],["mean_error_level","residual_error_level"]),"quantile_graft":summarize_grid(frames["quantile_regime"],["marginal_error_level","rank_corruption_fraction"]),"spatial_transplant":summarize_grid(frames["spatial_regime"],["expression_corruption","matching_noise"])}; (out_dir/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    b=frames["official_floor_baselines"]; a=frames["spatial_assignment"]; m=frames["mixture_regime"]
    md=["# Ensemble regime-map results","",f"Scorer pinned to `aristoteleo/veckit@{VECKIT_COMMIT}`.","","These use the organizers' public mini targets. The exact cases in `RESULTS.md` remain implementation checks; here the parents are only imperfectly complementary.","","`primary_win_fraction` is the fraction of task primary metrics on which the blend is strictly better than both parents. T1 uses DE score, DE direction, MMD and variogram. T2 also includes d2 shape, sliced Wasserstein, occupancy Dice and neighborhood MMD.","","## Official floor baselines","","The challenge defines `copy_last` as the T1/T2 floor and `wt_identity` as the T3 floor.","",b[["task","baseline","de_score","de_direction","mmd_u","variogram"]].to_markdown(index=False),"","## Mean graft","",f"Summary: `{json.dumps(summary['mean_graft'])}`","","![Mean graft regime map](regime_results/mean_regime.png)","","## Quantile graft","",f"Summary: `{json.dumps(summary['quantile_graft'])}`","","![Quantile graft regime map](regime_results/quantile_regime.png)","","## Spatial transplant","",f"Summary: `{json.dumps(summary['spatial_transplant'])}`","","![Spatial transplant regime map](regime_results/spatial_regime.png)","","### Hungarian versus greedy", "",a[["matching_noise","assignment","coordinate_rmse","mean_match_distance","sliced_wasserstein","occupancy_dice","neighborhood_mmd"]].to_markdown(index=False),"","## Population mixtures","","Whole-cell mixtures have no factor-preservation guarantee, so the table varies parent complementarity and alpha directly.","",m[["complementarity_severity","alpha","primary_wins_vs_both","primary_losses_vs_both","primary_win_fraction"]].to_markdown(index=False),"","## Raw outputs","","Every grid cell and parent/blend metric is in `regime_results/`. Reproduce with:","","```bash","pip install -r requirements.txt","python regime_map.py --out-dir regime_results","```",""]
    Path("REGIME_RESULTS.md").write_text("\n".join(md),encoding="utf-8")


def main():
    p=argparse.ArgumentParser(); p.add_argument("--data-dir",type=Path,default=Path(".cache/public_samples")); p.add_argument("--out-dir",type=Path,default=Path("regime_results")); args=p.parse_args(); samples=download_public_samples(args.data_dir)
    with tempfile.TemporaryDirectory(prefix="vec_regime_") as tmp:
        work=Path(tmp); baselines=baseline_rows(samples,work); mean=t1_mean_regime(samples,work); quant=t1_quantile_regime(samples,work); spatial,assign=t2_spatial_regime(samples,work); mix=mixture_regime(samples,work)
    write_outputs(args.out_dir,baselines,mean,quant,spatial,assign,mix)


if __name__=="__main__": main()
