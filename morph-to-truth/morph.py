#!/usr/bin/env python
"""Pair predicted cells with true cells and show how far each one has to move.

Inputs are two .h5ad files with obsm["spatial_3D"] in micrometres. The script
subsamples both, aligns the two clouds, matches cells one to one, and writes:

  morph.mp4      each predicted cell travels to its matched true position
  summary.png    where the misplaced cells are, and which cell types they are
  matches.csv    one row per matched pair
  summary.json   headline numbers

Example:
  python morph.py PRED.h5ad TRUTH.h5ad --out DIR
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree
from scipy.spatial.distance import cdist

HERE = Path(__file__).resolve().parent
TIMELAPSE = HERE.parent / "embryo-timelapse"
if str(TIMELAPSE) not in sys.path:
    sys.path.insert(0, str(TIMELAPSE))

import render as R  # noqa: E402  (turntable, palette, scene layout and ffmpeg pipe)

import matplotlib.colors as mcolors  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

FLIPS = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]  # the four sign patterns with det +1
N_PCS = 20                  # expression PCs, fitted on the truth
TYPE_MIN_CELLS = 20         # bar chart: types with at least this many true cells
TOP_TYPES = 15
GHOST = "#d6d6d6"
TEXT, SUBTLE, RULE, BAR = "#1f1f1f", "#666666", "#cfcfcf", "#4d4d4d"
RAMP = mcolors.LinearSegmentedColormap.from_list("displacement", ["#e8e8e8", "#8c2d04"])
HOLD_FRACTION = 0.15        # each hold is 15% of the clip: 1.5 s of a 10 s clip
ICP_ITERS = 30              # rigid ICP: at most this many rounds per candidate
ICP_TOL = 1e-3              # ... or stop when chamfer changes by less than 0.1%
MIN_SHARED_LABELS = 5       # below this many shared cell-type labels, no mismatch rate


# --------------------------------------------------------------------------- data

@dataclass
class Cloud:
    name: str
    n_total: int                 # cells in the file
    rows: np.ndarray             # file row of each kept cell
    xyz: np.ndarray              # (n, 3) micrometres
    labels: np.ndarray | None    # cell-type string per kept cell, if obs["celltype"] exists
    counts: pd.Series | None     # cell-type counts over the whole file
    X: np.ndarray | None         # (n, genes) expression as stored, dense float64
    genes: list | None

    def take(self, idx) -> "Cloud":
        return Cloud(self.name, self.n_total, self.rows[idx], self.xyz[idx],
                     None if self.labels is None else self.labels[idx], self.counts,
                     None if self.X is None else self.X[idx], self.genes)


def load_cloud(path, n_cells: int, seed: int) -> Cloud:
    """Read coordinates, labels and expression for a random subsample (backed read)."""
    import anndata as ad

    path = Path(path)
    a = ad.read_h5ad(path, backed="r")
    try:
        if "spatial_3D" not in a.obsm.keys():
            raise SystemExit(f"{path.name}: no obsm['spatial_3D'] (micrometres)")
        allxyz = np.asarray(a.obsm["spatial_3D"][:], dtype=np.float64)[:, :3]
        pool = np.flatnonzero(np.isfinite(allxyz).all(axis=1))
        if pool.size == 0:
            raise SystemExit(f"{path.name}: no finite spatial_3D coordinates")
        rng = np.random.default_rng(seed)
        rows = np.sort(rng.choice(pool, size=min(n_cells, pool.size), replace=False))

        labels = counts = None
        if "celltype" in a.obs.columns:
            full = a.obs["celltype"].astype(str).to_numpy()
            counts = pd.Series(full).value_counts()
            labels = full[rows]

        X = genes = None
        if a.X is not None:
            part = a.X[rows]
            X = np.asarray(part.toarray() if sp.issparse(part) else part, dtype=np.float64)
            genes = [str(g) for g in a.var_names]
    finally:
        a.file.close()
    return Cloud(path.stem, int(allxyz.shape[0]), rows, allxyz[rows], labels, counts, X, genes)


# --------------------------------------------------------------------------- alignment

def chamfer(A: np.ndarray, B: np.ndarray) -> float:
    """Symmetric mean nearest-neighbour distance between two clouds (micrometres)."""
    d_ab = cKDTree(B).query(A)[0]
    d_ba = cKDTree(A).query(B)[0]
    return 0.5 * (float(d_ab.mean()) + float(d_ba.mean()))


def _rms(P: np.ndarray) -> float:
    return float(np.sqrt((P ** 2).sum(axis=1).mean()))


def icp(P: np.ndarray, T: np.ndarray, max_iter: int = ICP_ITERS, tol: float = ICP_TOL):
    """Rigid ICP: nearest-neighbour pairs, Kabsch rotation with det +1, then translation.

    Stops after max_iter rounds or when the chamfer distance changes by less than tol
    (relative). Returns the moved cloud and its chamfer distance to T. The best
    iterate is kept, so a round that makes the fit worse is discarded.
    """
    tree = cKDTree(T)
    best_P, best_ch = P, chamfer(P, T)
    prev = best_ch
    for _ in range(max_iter):
        _, idx = tree.query(P)
        Q = T[idx]
        Pc, Qc = P.mean(axis=0), Q.mean(axis=0)
        U, _, Vt = np.linalg.svd((P - Pc).T @ (Q - Qc))
        Rm = Vt.T @ U.T
        if np.linalg.det(Rm) < 0:              # force a proper rotation
            Vt[-1] *= -1.0
            Rm = Vt.T @ U.T
        P = (P - Pc) @ Rm.T + Qc
        ch = chamfer(P, T)
        if ch < best_ch:
            best_P, best_ch = P, ch
        if abs(prev - ch) <= tol * prev:
            break
        prev = ch
    return best_P, best_ch


def align(pred_xyz: np.ndarray, true_xyz: np.ndarray, rescale: bool = False) -> dict:
    """Put the predicted cloud on the true cloud, with a rigid ICP refinement.

    Candidate starts: (a) both clouds centred, no rotation; (b) both clouds in their
    PCA frames, with each of the four proper sign patterns applied to the prediction.
    Each candidate is refined by ICP. The candidate with the lowest chamfer distance
    after ICP wins. The winner is then rotated (same rotation for both clouds) into the
    truth's PCA frame for display, which changes no distances.
    The scale is kept unless rescale=True, which matches the RMS radius of the two clouds.
    """
    c_t = true_xyz.mean(axis=0)
    c_p = pred_xyz.mean(axis=0)
    unaligned = chamfer(true_xyz - c_t, pred_xyz - c_p)

    rot_t, _ = R.pca_frame(true_xyz)
    rot_p, _ = R.pca_frame(pred_xyz)
    truth_pca = R.to_frame(true_xyz, rot_t, c_t)
    pred_pca = R.to_frame(pred_xyz, rot_p, c_p)
    truth_raw, pred_raw = true_xyz - c_t, pred_xyz - c_p

    scale = 1.0
    if rescale:
        scale = _rms(truth_raw) / _rms(pred_raw)   # rotation-invariant, so the same for both frames

    cands = [("identity", None, pred_raw, truth_raw)]
    for flip in FLIPS:
        cands.append(("pca", flip, pred_pca * np.asarray(flip, dtype=float), truth_pca))

    rows = []
    for name, flip, P0, T in cands:
        P0 = P0 * scale
        pre = chamfer(P0, T)
        P1, post = icp(P0, T)
        rows.append({"name": name, "flip": flip, "pre": pre, "icp": post, "P": P1, "T": T})

    best = min(rows, key=lambda r: r["icp"])
    rot_d, _ = R.pca_frame(best["T"])               # display rotation, applied to both clouds
    truth_frame = best["T"] @ rot_d
    pred_frame = best["P"] @ rot_d
    return {
        "pred": pred_frame, "truth": truth_frame,
        "winner": best["name"], "flip": None if best["flip"] is None else tuple(best["flip"]),
        "unaligned": unaligned,
        "best_pre_icp": min(r["pre"] for r in rows),
        "after_icp": best["icp"],
        "candidates": {
            ("identity" if r["flip"] is None else f"pca{tuple(r['flip'])}"):
                {"pre_icp": round(r["pre"], 3), "after_icp": round(r["icp"], 3)} for r in rows
        },
        "rescale": scale,
    }


# --------------------------------------------------------------------------- matching

def expression_pcs(X_true: np.ndarray, X_pred: np.ndarray, n_pcs: int = N_PCS):
    """Project both expression matrices onto PCs fitted on the truth."""
    mu = X_true.mean(axis=0)
    _, _, vt = np.linalg.svd(X_true - mu, full_matrices=False)
    V = vt[: min(n_pcs, vt.shape[0])].T
    return (X_true - mu) @ V, (X_pred - mu) @ V


def match(pred_pos, true_pos, Zp=None, Zt=None, lam: float = 0.5):
    """One-to-one assignment. Cost = position distance / median + lam * expression distance / median.

    Each distance is divided by the median of all pairwise distances of its kind.
    With lam = 0 the match is pure geometry. Returns cols, where cols[i] is the true
    index matched to predicted cell i.
    """
    d_pos = cdist(pred_pos, true_pos)
    pos_scale = max(float(np.median(d_pos)), 1e-12)
    cost = d_pos / pos_scale
    info = {"pos_scale_um": pos_scale, "expr_scale": None}
    if lam > 0:
        d_exp = cdist(Zp, Zt)
        expr_scale = max(float(np.median(d_exp)), 1e-12)
        cost = cost + lam * d_exp / expr_scale
        info["expr_scale"] = expr_scale
    _, cols = linear_sum_assignment(cost)
    return cols, info


@dataclass
class Result:
    pred: Cloud
    truth: Cloud
    pred_frame: np.ndarray       # predicted cells after alignment, truth frame, micrometres
    truth_frame: np.ndarray      # true cells, truth frame
    cols: np.ndarray             # cols[i] = true index matched to predicted cell i
    disp: np.ndarray             # displacement of each predicted cell to its match (um)
    align_info: dict
    match_info: dict
    lam: float
    n_pcs: int


def run_match(pred: Cloud, truth: Cloud, lam: float = 0.5, rescale: bool = False) -> Result:
    if pred.xyz.shape[0] != truth.xyz.shape[0]:
        raise SystemExit("prediction and truth must have the same number of subsampled cells")
    if lam > 0 and (pred.X is None or truth.X is None):
        raise SystemExit("expression is needed for --lam > 0; a file has no .X (use --lam 0)")

    al = align(pred.xyz, truth.xyz, rescale)
    Zp = Zt = None
    n_pcs = 0
    if lam > 0:
        pos = {g: i for i, g in enumerate(pred.genes)}
        common = [g for g in truth.genes if g in pos]
        if not common:
            raise SystemExit("prediction and truth share no genes")
        it = [truth.genes.index(g) for g in common]
        ip = [pos[g] for g in common]
        Zt, Zp = expression_pcs(truth.X[:, it], pred.X[:, ip])
        n_pcs = Zt.shape[1]

    cols, mi = match(al["pred"], al["truth"], Zp, Zt, lam)
    disp = np.linalg.norm(al["pred"] - al["truth"][cols], axis=1)
    return Result(pred, truth, al["pred"], al["truth"], cols, disp, al, mi, lam, n_pcs)


# --------------------------------------------------------------------------- summary

def summarise(res: Result, cli: dict) -> dict:
    disp_true = np.empty_like(res.disp)
    disp_true[res.cols] = res.disp              # displacement indexed by true cell

    # Cell-type vocabularies. Label strings can differ between files (different atlases
    # or stages), so a mismatch is only scored where both labels are in the shared vocabulary.
    vocab = {"pred_label_count": None, "truth_label_count": None, "shared_label_count": None,
             "shared_labels": [], "only_in_pred": [], "only_in_truth": []}
    mismatch = None
    compared = 0
    raw_rate = None
    status = "not computed: a file has no obs['celltype']"
    if res.pred.counts is not None and res.truth.counts is not None:
        pv = set(res.pred.counts.index.astype(str))
        tv = set(res.truth.counts.index.astype(str))
        shared = sorted(pv & tv)
        vocab.update({"pred_label_count": len(pv), "truth_label_count": len(tv),
                      "shared_label_count": len(shared), "shared_labels": shared,
                      "only_in_pred": sorted(pv - tv), "only_in_truth": sorted(tv - pv)})
        pl = res.pred.labels
        tl = res.truth.labels[res.cols]
        differ = pl != tl
        raw_rate = float(differ.mean())                  # all pairs, labels taken as strings
        in_shared = np.isin(pl, shared) & np.isin(tl, shared)
        compared = int(in_shared.sum())
        if len(shared) < MIN_SHARED_LABELS:
            status = (f"not available: only {len(shared)} shared labels "
                      f"(need {MIN_SHARED_LABELS})")
        elif compared == 0:
            status = "not available: no matched pair has both labels in the shared vocabulary"
        else:
            mismatch = float(differ[in_shared].mean())
            status = "computed over matched pairs whose two labels are both in the shared vocabulary"

    per_type = {}
    if res.truth.labels is not None:
        df = pd.DataFrame({"type": res.truth.labels, "um": disp_true})
        for t, g in df.groupby("type")["um"]:
            per_type[str(t)] = {"n_true": int(g.size), "median_um": round(float(g.median()), 3)}

    al = res.align_info
    mi = res.match_info
    return {
        **cli,
        "n_cells": int(res.disp.size),
        "pred_cells_in_file": res.pred.n_total,
        "truth_cells_in_file": res.truth.n_total,
        "lam": res.lam,
        "expr_pcs": res.n_pcs,
        "alignment": {
            "winner": al["winner"],                      # "identity" or "pca"
            "flip": None if al["flip"] is None else list(al["flip"]),
            "chamfer_unaligned_um": round(al["unaligned"], 3),
            "chamfer_best_candidate_um": round(al["best_pre_icp"], 3),
            "chamfer_after_icp_um": round(al["after_icp"], 3),
            "candidates": al["candidates"],              # pre-ICP and post-ICP chamfer per start
            "icp_iters_max": ICP_ITERS,
            "icp_tol_rel": ICP_TOL,
        },
        "rescale_factor": round(al["rescale"], 6),
        "pos_scale_um": round(mi["pos_scale_um"], 4),
        "expr_scale": None if mi["expr_scale"] is None else round(mi["expr_scale"], 4),
        "median_displacement_um": round(float(np.median(res.disp)), 3),
        "p90_displacement_um": round(float(np.percentile(res.disp, 90)), 3),
        "vocabulary": vocab,
        "mismatch_rate": None if mismatch is None else round(mismatch, 4),
        "mismatch_status": status,
        "mismatch_pairs_compared": compared,
        "label_difference_rate_all_pairs": None if raw_rate is None else round(raw_rate, 4),
        "per_type": per_type,
    }


def write_matches(res: Result, path: Path) -> None:
    n = res.disp.size
    pl = res.pred.labels if res.pred.labels is not None else np.full(n, "", dtype=object)
    tl = res.truth.labels[res.cols] if res.truth.labels is not None else np.full(n, "", dtype=object)
    pd.DataFrame({
        "pred_index": res.pred.rows,
        "true_index": res.truth.rows[res.cols],
        "displacement_um": np.round(res.disp, 4),
        "pred_celltype": pl,
        "true_celltype": tl,
    }).to_csv(path, index=False)


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(RULE)
        ax.spines[side].set_linewidth(0.6)
    ax.tick_params(colors=SUBTLE, labelsize=8, width=0.6, color=RULE)


def write_summary_png(res: Result, summary: dict, path: Path) -> None:
    fig = Figure(figsize=(12.8, 7.2), dpi=100, facecolor="white")
    FigureCanvasAgg(fig)
    med, p90 = summary["median_displacement_um"], summary["p90_displacement_um"]
    mm = summary["mismatch_rate"]
    if mm is None:
        mm_txt = "type mismatch not available"
    else:
        mm_txt = f"type mismatch {mm:.0%} on {summary['mismatch_pairs_compared']:,} shared-label pairs"
    fig.text(0.03, 0.955, f"Where and which cell types are misplaced: {res.pred.name} vs {res.truth.name}",
             fontsize=14, color=TEXT, va="top")
    fig.text(0.03, 0.915, f"{res.disp.size:,} cells paired one to one  ·  median {med:.1f} µm  ·  "
             f"90th percentile {p90:.1f} µm  ·  {mm_txt}", fontsize=10, color=SUBTLE, va="top")

    # left: truth cloud on its first two PCs, coloured by the displacement of its match
    disp_true = np.empty_like(res.disp)
    disp_true[res.cols] = res.disp
    vmax = max(float(np.percentile(res.disp, 99)), 1e-9)
    ax = fig.add_axes([0.07, 0.17, 0.36, 0.62])
    sc = ax.scatter(res.truth_frame[:, 0], res.truth_frame[:, 1], c=disp_true, cmap=RAMP,
                    vmin=0, vmax=vmax, s=7, linewidths=0)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("first principal axis of truth (µm)", fontsize=9, color=SUBTLE)
    ax.set_ylabel("second principal axis (µm)", fontsize=9, color=SUBTLE)
    _style(ax)
    fig.text(0.07, 0.855, "Truth cells on their first two PCs, coloured by how far their match moved",
             fontsize=11, color=TEXT, va="top")
    cax = fig.add_axes([0.07, 0.085, 0.36, 0.014])
    cb = fig.colorbar(sc, cax=cax, orientation="horizontal")
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=8, colors=SUBTLE, length=0)
    cb.set_label(f"displacement (µm); colour is clipped at the 99th percentile, {vmax:.1f} µm",
                 fontsize=9, color=SUBTLE)

    # right: median displacement by true cell type
    fig.text(0.62, 0.855, f"Median displacement by true cell type (top {TOP_TYPES}, "
             f"at least {TYPE_MIN_CELLS} cells)", fontsize=11, color=TEXT, va="top")
    ax2 = fig.add_axes([0.62, 0.17, 0.33, 0.62])
    if summary["per_type"]:
        eligible = [(t, v) for t, v in summary["per_type"].items() if v["n_true"] >= TYPE_MIN_CELLS]
        eligible.sort(key=lambda kv: -kv[1]["median_um"])
        top = eligible[:TOP_TYPES]
        y = np.arange(len(top))
        vals = np.array([v["median_um"] for _, v in top])
        ax2.barh(y, vals, color=BAR, height=0.62)
        ax2.set_yticks(y)
        ax2.set_yticklabels([f"{t} ({v['n_true']})" for t, v in top], fontsize=9, color=TEXT)
        ax2.invert_yaxis()
        for yi, val in zip(y, vals):
            ax2.text(val + 0.01 * max(vals.max(), 1e-9), yi, f"{val:.1f}", va="center", fontsize=8, color=SUBTLE)
        ax2.set_xlim(0, max(vals.max(), 1e-9) * 1.15)
        ax2.set_xlabel("median displacement (µm); number of true cells in brackets", fontsize=9, color=SUBTLE)
        _style(ax2)
        ax2.spines["left"].set_visible(False)
        ax2.tick_params(axis="y", length=0)
    else:
        fig.text(0.62, 0.5, "No cell-type labels in the truth file.", fontsize=10, color=SUBTLE)
    v = summary["vocabulary"]
    if mm is not None:
        fig.text(0.62, 0.115, f"Predicted type differs from true type for {mm:.1%} of "
                 f"{summary['mismatch_pairs_compared']:,} pairs.", fontsize=9, color=TEXT, va="top")
        fig.text(0.62, 0.085, f"Only pairs whose two labels are both among the "
                 f"{v['shared_label_count']} shared types are counted.", fontsize=9, color=SUBTLE, va="top")
    elif v["shared_label_count"] is not None:
        fig.text(0.62, 0.115, f"Type mismatch not available: the two files share "
                 f"{v['shared_label_count']} cell-type labels (need {MIN_SHARED_LABELS}).",
                 fontsize=9, color=TEXT, va="top")
    fig.savefig(path, dpi=100, facecolor="white")


# --------------------------------------------------------------------------- video

def _text(fig, cv, x, y, s, size, colour, ha="left"):
    fig.text(cv.fx(x), cv.fy(y), s, fontsize=cv.pt(size), color=colour, ha=ha, va="top")


def _displacement_colourbar(scene, vmax: float) -> None:
    cv, fig = scene.cv, scene.fig
    x, y, w = 1030, 130, 200
    _text(fig, cv, x, y - 16, "displacement to match (µm)", 9, R.LEGEND_TEXT)
    ax = fig.add_axes([cv.fx(x), cv.fy(y + 10), w / R.BASE_W, 10 / R.BASE_H])
    ax.imshow(np.linspace(0, 1, 256)[None, :], aspect="auto", cmap=RAMP, extent=(0, 1, 0, 1))
    ax.set_axis_off()
    _text(fig, cv, x, y + 14, "0", 8, R.LEGEND_TEXT)
    _text(fig, cv, x + w, y + 14, f"{vmax:.0f} µm (p99)", 8, R.LEGEND_TEXT, ha="right")


def render_video(res: Result, out: Path, seconds: float, fps: int) -> None:
    """Hold the prediction, move every cell to its match, hold the truth. Grey ghost = truth."""
    cv = R.Canvas()
    colours = R.Colours(TIMELAPSE / "palette.json")
    N = res.disp.size
    target = res.truth_frame[res.cols]

    if res.pred.labels is not None:
        pred_stage = R.Stage(name=res.pred.name, xyz=res.pred.xyz, P=res.pred_frame,
                             n_total=res.pred.n_total, labels=res.pred.labels)
        moving_rgba = R.stage_rgba(pred_stage, colours)
        legend, more = R.legend_items(res.pred.counts, colours)
        colour_note = "colour: predicted cell type"
        vmax = None
    else:
        vmax = max(float(np.percentile(res.disp, 99)), 1e-9)
        moving_rgba = RAMP(np.clip(res.disp / vmax, 0.0, 1.0))
        moving_rgba[:, 3] = R.ALPHA
        legend = more = None
        colour_note = "colour: displacement to match"

    truth_stage = R.Stage(name=res.truth.name, xyz=res.truth.xyz, P=res.truth_frame,
                          n_total=res.truth.n_total)
    ghost = np.tile(np.asarray(mcolors.to_rgba(GHOST)), (N, 1))
    scale = R.frame_scale(cv, [R.radius99(res.truth_frame), R.radius99(res.pred_frame)])
    subtitle = f"{N:,} cells paired one to one  ·  grey: true cells  ·  {colour_note}"
    scene = R.Scene(cv, [R.PanelSpec(stage=truth_stage, title="", subtitle=subtitle, rgba=ghost)],
                    scale, legend=legend, more=more)
    if vmax is not None:
        _displacement_colourbar(scene, vmax)
    title_artist = scene.fig.texts[0]
    moving = scene.points[0].ax.scatter([], [], s=R.POINT_SIZE, linewidths=0)

    total = max(3, round(seconds * fps))
    hold = max(1, round(HOLD_FRACTION * seconds * fps))
    n_move = total - 2 * hold
    if n_move < 1:
        raise SystemExit("--seconds is too short for two holds and a move")

    video = R.Video(out, fps, cv.w, cv.h)
    try:
        for i in range(total):
            theta = np.pi * i / total                  # half a turn over the whole clip
            if i < hold:
                e, title = 0.0, f"Prediction: {res.pred.name}"
            elif i < hold + n_move:
                e = (i - hold + 1) / n_move            # linear in time
                title = f"Moving each cell to its matched {res.truth.name} position"
            else:
                e, title = 1.0, f"Truth: {res.truth.name}"
            P = (1.0 - e) * res.pred_frame + e * target
            h, v, depth = R.project(P, theta)
            order = np.argsort(depth, kind="stable")
            moving.set_offsets(np.column_stack((h[order], v[order])))
            moving.set_facecolor(moving_rgba[order])
            title_artist.set_text(title)
            video.write(scene.render(theta))
    finally:
        video.close()


# --------------------------------------------------------------------------- CLI

def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("pred", type=Path, help="predicted .h5ad (obsm['spatial_3D'], micrometres)")
    ap.add_argument("truth", type=Path, help="true .h5ad (obsm['spatial_3D'], micrometres)")
    ap.add_argument("--out", required=True, type=Path, help="output folder")
    ap.add_argument("--cells", type=int, default=3000, help="subsample each file to this many cells")
    ap.add_argument("--lam", type=float, default=0.5, help="weight of expression in the match (0 = geometry only)")
    ap.add_argument("--rescale", action="store_true", help="match the RMS radius of the two clouds before alignment")
    ap.add_argument("--seconds", type=float, default=10.0, help="length of the video")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0, help="subsampling seed")
    ap.add_argument("--no-video", action="store_true", help="skip morph.mp4")
    args = ap.parse_args(argv)

    pred = load_cloud(args.pred, args.cells, args.seed)
    truth = load_cloud(args.truth, args.cells, args.seed)
    m = min(len(pred.rows), len(truth.rows))      # 1:1 needs equal counts
    if len(pred.rows) != m:
        keep = np.sort(np.random.default_rng(args.seed + 1).choice(len(pred.rows), m, replace=False))
        pred = pred.take(keep)
    if len(truth.rows) != m:
        keep = np.sort(np.random.default_rng(args.seed + 1).choice(len(truth.rows), m, replace=False))
        truth = truth.take(keep)

    res = run_match(pred, truth, lam=args.lam, rescale=args.rescale)
    cli = {"pred_file": pred.name, "truth_file": truth.name, "cells_requested": args.cells,
           "seed": args.seed, "rescale_requested": bool(args.rescale)}
    summary = summarise(res, cli)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    write_matches(res, out / "matches.csv")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_summary_png(res, summary, out / "summary.png")
    if not args.no_video:
        render_video(res, out / "morph.mp4", args.seconds, args.fps)

    al = summary["alignment"]
    print(f"N={summary['n_cells']} winner={al['winner']} flip={al['flip']} chamfer unaligned "
          f"{al['chamfer_unaligned_um']:.1f} -> best candidate {al['chamfer_best_candidate_um']:.1f}"
          f" -> after ICP {al['chamfer_after_icp_um']:.1f} um")
    print(f"median displacement {summary['median_displacement_um']:.1f} um, "
          f"p90 {summary['p90_displacement_um']:.1f} um")
    v = summary["vocabulary"]
    if v["shared_label_count"] is not None:
        print(f"labels: pred {v['pred_label_count']}, truth {v['truth_label_count']}, "
              f"shared {v['shared_label_count']} {v['shared_labels']}")
        print(f"  only in pred ({len(v['only_in_pred'])}): {v['only_in_pred']}")
        print(f"  only in truth ({len(v['only_in_truth'])}): {v['only_in_truth']}")
    print(f"type mismatch: {summary['mismatch_rate']} over {summary['mismatch_pairs_compared']} pairs "
          f"({summary['mismatch_status']})")
    print(f"wrote {out}")
    return summary


if __name__ == "__main__":
    main()
