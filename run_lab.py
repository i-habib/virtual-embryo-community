from __future__ import annotations

import argparse
import json
import tempfile
import urllib.request
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from vec_blender.methods import (
    mean_graft,
    population_mix,
    quantile_graft,
    spatial_transplant,
)
from veckit import score


VECKIT_COMMIT = "46d41e63f42a9aab815db20b742feeccd249cb17"
RAW_BASE = f"https://raw.githubusercontent.com/aristoteleo/veckit/{VECKIT_COMMIT}/data/"
FILES = [
    "sample_8.5.h5ad",
    "sample_9.5.h5ad",
    "sample_heart_9.25.h5ad",
    "sample_heart_9.5.h5ad",
    "sample_wt.h5ad",
    "sample_mab21l2_ko.h5ad",
]


def dense(a: ad.AnnData) -> np.ndarray:
    return (
        a.X.toarray().astype(np.float64)
        if sparse.issparse(a.X)
        else np.asarray(a.X, dtype=np.float64)
    )


def download_public_samples(data_dir: Path) -> dict[str, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in FILES:
        path = data_dir / name
        if not path.exists():
            urllib.request.urlretrieve(RAW_BASE + name, path)
        out[name] = path
    return out


def align_to(a: ad.AnnData, genes) -> ad.AnnData:
    genes = list(map(str, genes))
    if set(map(str, a.var_names)) != set(genes):
        raise ValueError("public examples do not share the same gene panel")
    return a[:, genes]


def make_like(
    template: ad.AnnData,
    X: np.ndarray,
    *,
    coords: np.ndarray | None = None,
    prefix: str,
) -> ad.AnnData:
    X = np.asarray(X, dtype=np.float32)
    out = ad.AnnData(X=X, var=template.var.copy())
    out.var_names = template.var_names.copy()
    out.obs_names = [f"{prefix}_{i:05d}" for i in range(len(X))]
    if coords is not None:
        out.obsm["spatial_3D"] = np.asarray(coords, dtype=np.float32)
    return out


def save_and_score(
    pred: ad.AnnData,
    *,
    name: str,
    task: str,
    work: Path,
    target: Path,
    reference: Path | None = None,
    wt: Path | None = None,
) -> dict:
    X = dense(pred)
    if not np.isfinite(X).all():
        raise ValueError(f"{name}: prediction contains non-finite expression values")
    if np.min(X) < -1e-7:
        raise ValueError(
            f"{name}: prediction contains negative expression values "
            f"(min={float(np.min(X)):.6g})"
        )

    path = work / f"{name}.h5ad"
    pred.write_h5ad(path)
    kwargs = {}
    if reference is not None:
        kwargs["reference"] = reference
    if wt is not None:
        kwargs["wt"] = wt
    if task == "T2":
        kwargs["setting"] = "heart"
    result = score(task=task, input=path, target=target, **kwargs)
    return {"candidate": name, **result["metrics"]}


def positive_offset(X: np.ndarray) -> np.ndarray:
    """A deterministic nonnegative gene-wise offset large enough to move the mean."""
    return 0.25 + 0.5 * np.std(X, axis=0)


def t1_mean_structure(samples, work, rng):
    target_path = samples["sample_9.5.h5ad"]
    ref_path = samples["sample_8.5.h5ad"]
    target = ad.read_h5ad(target_path)
    X = dense(target)

    mu_t = X.mean(0)
    offset = positive_offset(X)
    a = make_like(
        target,
        np.repeat(mu_t[None, :], target.n_obs, axis=0),
        prefix="t1_mean",
    )
    # Adding one value per gene changes pseudobulk while leaving every centered
    # cell residual exactly unchanged, and it stays scorer-valid/nonnegative.
    b = make_like(target, X + offset[None, :], prefix="t1_structure")
    blend = mean_graft(a, b).adata

    rows = [
        save_and_score(
            a,
            name="A_correct_mean_collapsed",
            task="T1",
            work=work,
            target=target_path,
            reference=ref_path,
        ),
        save_and_score(
            b,
            name="B_structure_wrong_mean",
            task="T1",
            work=work,
            target=target_path,
            reference=ref_path,
        ),
        save_and_score(
            blend,
            name="mean_graft",
            task="T1",
            work=work,
            target=target_path,
            reference=ref_path,
        ),
    ]
    diagnostics = {
        "offset_min": float(np.min(offset)),
        "offset_max": float(np.max(offset)),
        "blend_expression_rmse_to_target": float(
            np.sqrt(np.mean((dense(blend) - X) ** 2))
        ),
        "blend_max_abs_expression_error": float(
            np.max(np.abs(dense(blend) - X))
        ),
    }

    mix_rows = []
    for alpha in (0.0, 0.25, 0.5, 0.75, 1.0):
        mixed = population_mix(
            a, b, alpha=alpha, n_out=target.n_obs, seed=0
        ).adata
        mix_rows.append(
            save_and_score(
                mixed,
                name=f"mixture_alpha_{alpha:g}",
                task="T1",
                work=work,
                target=target_path,
                reference=ref_path,
            )
        )
    return rows, mix_rows, diagnostics


def t1_quantile(samples, work, rng):
    target_path = samples["sample_9.5.h5ad"]
    ref_path = samples["sample_8.5.h5ad"]
    target = ad.read_h5ad(target_path)
    X = dense(target)
    n, g = X.shape

    Xa = np.empty_like(X)
    for j in range(g):
        Xa[:, j] = X[rng.permutation(n), j]

    scale = 0.55 + 0.9 * (np.arange(g) + 1) / max(g, 1)
    # Strictly positive offset keeps zero-valued target entries nonnegative.
    shift = 0.25 + 0.15 * np.sin(np.arange(g) * 0.17)
    Xb = X * scale[None, :] + shift[None, :]

    a = make_like(target, Xa, prefix="t1_marginal")
    b = make_like(target, Xb, prefix="t1_ranks")
    blend = quantile_graft(a, b).adata

    rows = [
        save_and_score(
            a,
            name="A_correct_marginals_shuffled",
            task="T1",
            work=work,
            target=target_path,
            reference=ref_path,
        ),
        save_and_score(
            b,
            name="B_correct_ranks_wrong_marginals",
            task="T1",
            work=work,
            target=target_path,
            reference=ref_path,
        ),
        save_and_score(
            blend,
            name="quantile_graft",
            task="T1",
            work=work,
            target=target_path,
            reference=ref_path,
        ),
    ]
    diagnostics = {
        "distorted_expression_min": float(np.min(Xb)),
        "blend_expression_rmse_to_target": float(
            np.sqrt(np.mean((dense(blend) - X) ** 2))
        ),
        "blend_max_abs_expression_error": float(
            np.max(np.abs(dense(blend) - X))
        ),
    }
    return rows, diagnostics


def t2_spatial(samples, work, rng):
    target_path = samples["sample_heart_9.5.h5ad"]
    ref_path = samples["sample_heart_9.25.h5ad"]
    target = ad.read_h5ad(target_path)
    X = dense(target)
    C = np.asarray(target.obsm["spatial_3D"], dtype=np.float64)[:, :3]
    n, g = X.shape

    coord_perm = rng.permutation(n)
    a = make_like(target, X, coords=C[coord_perm], prefix="t2_expression")

    row_perm = rng.permutation(n)
    gene_scale = np.std(X, axis=0)
    shift = 0.35 + 0.65 * gene_scale
    b = make_like(
        target,
        X[row_perm] + shift[None, :],
        coords=C[row_perm],
        prefix="t2_geometry",
    )

    blend_result = spatial_transplant(
        a,
        b,
        seed=0,
        n_components=min(24, g),
        assignment="hungarian",
    )
    blend = blend_result.adata

    rows = [
        save_and_score(
            a,
            name="A_expression_wrong_locations",
            task="T2",
            work=work,
            target=target_path,
            reference=ref_path,
        ),
        save_and_score(
            b,
            name="B_geometry_shifted_expression",
            task="T2",
            work=work,
            target=target_path,
            reference=ref_path,
        ),
        save_and_score(
            blend,
            name="spatial_transplant",
            task="T2",
            work=work,
            target=target_path,
            reference=ref_path,
        ),
    ]
    diagnostics = {
        **blend_result.report,
        "blend_expression_rmse_to_target": float(
            np.sqrt(np.mean((dense(blend) - X) ** 2))
        ),
        "blend_coordinate_rmse_to_target": float(
            np.sqrt(
                np.mean(
                    (np.asarray(blend.obsm["spatial_3D"]) - C) ** 2
                )
            )
        ),
        "blend_max_coordinate_error": float(
            np.max(np.abs(np.asarray(blend.obsm["spatial_3D"]) - C))
        ),
    }
    return rows, diagnostics


def t3_response_structure(samples, work, rng):
    target_path = samples["sample_mab21l2_ko.h5ad"]
    wt_path = samples["sample_wt.h5ad"]
    target = ad.read_h5ad(target_path)
    X = dense(target)
    C = (
        np.asarray(target.obsm["spatial_3D"], dtype=np.float64)[:, :3]
        if "spatial_3D" in target.obsm
        else None
    )

    mu_t = X.mean(0)
    offset = positive_offset(X)
    a = make_like(
        target,
        np.repeat(mu_t[None, :], target.n_obs, axis=0),
        coords=C,
        prefix="t3_response",
    )
    # Same KO centered structure, deliberately shifted perturbation mean.
    b = make_like(
        target,
        X + offset[None, :],
        coords=C,
        prefix="t3_structure",
    )
    blend = mean_graft(a, b).adata

    rows = [
        save_and_score(
            a,
            name="A_correct_mean_response_collapsed",
            task="T3",
            work=work,
            target=target_path,
            wt=wt_path,
        ),
        save_and_score(
            b,
            name="B_structure_shifted_response",
            task="T3",
            work=work,
            target=target_path,
            wt=wt_path,
        ),
        save_and_score(
            blend,
            name="mean_graft",
            task="T3",
            work=work,
            target=target_path,
            wt=wt_path,
        ),
    ]
    diagnostics = {
        "offset_min": float(np.min(offset)),
        "offset_max": float(np.max(offset)),
        "blend_expression_rmse_to_target": float(
            np.sqrt(np.mean((dense(blend) - X) ** 2))
        ),
        "blend_max_abs_expression_error": float(
            np.max(np.abs(dense(blend) - X))
        ),
    }
    return rows, diagnostics


def numeric_frame(rows):
    df = pd.DataFrame(rows)
    for c in df.columns:
        if c != "candidate":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def table_for_md(df: pd.DataFrame) -> str:
    show = df.copy()
    for c in show.columns:
        if c != "candidate":
            show[c] = show[c].map(
                lambda x: "" if pd.isna(x) else f"{float(x):.5g}"
            )
    return show.to_markdown(index=False)


def write_outputs(out_dir: Path, results: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, value in results.items():
        if key == "diagnostics":
            continue
        numeric_frame(value).to_csv(out_dir / f"{key}.csv", index=False)

    (out_dir / "diagnostics.json").write_text(
        json.dumps(results["diagnostics"], indent=2) + "\n"
    )

    md = [
        "# Ensemble Lab results",
        "",
        f"Scorer pinned to `aristoteleo/veckit@{VECKIT_COMMIT}`.",
        "",
        "These are controlled, target-aware experiments on the organizers' public mini examples. They test what a composition operation preserves; they are not hidden-board estimates.",
        "",
        "## T1: mean versus population structure",
        "",
        "A has the target pseudobulk mean but collapses every cell to that mean. B adds a positive gene-wise offset to the target, changing pseudobulk while leaving the centered cell cloud exactly unchanged. Mean grafting combines A's mean with B's centered population structure.",
        "",
        table_for_md(numeric_frame(results["t1_mean_structure"])),
        "",
        "Diagnostics:",
        "```json",
        json.dumps(results["diagnostics"]["t1_mean_structure"], indent=2),
        "```",
        "",
        "### Simple population-mixture sweep",
        "",
        table_for_md(numeric_frame(results["t1_mixture_sweep"])),
        "",
        "The mixture sweep interpolates between two empirical populations instead of replacing one factor exactly.",
        "",
        "## T1: marginals versus rank structure",
        "",
        "A preserves every gene's empirical marginal values but independently shuffles each gene across cells. B keeps the target's within-gene cell ranks while applying a positive gene-wise affine distortion. Quantile grafting takes A's values and assigns them according to B's ranks.",
        "",
        table_for_md(numeric_frame(results["t1_quantile"])),
        "",
        "Diagnostics:",
        "```json",
        json.dumps(results["diagnostics"]["t1_quantile"], indent=2),
        "```",
        "",
        "## T2: expression versus spatial assignment",
        "",
        "A contains the exact target expression with coordinates permuted across cells. B contains the exact target point cloud and coherent expression-coordinate pairing, but expression is shifted gene by gene and the rows are permuted. Spatial transplant matches the two expression clouds and copies B's matched coordinates onto A's expression cells.",
        "",
        table_for_md(numeric_frame(results["t2_spatial"])),
        "",
        "Diagnostics:",
        "```json",
        json.dumps(results["diagnostics"]["t2_spatial"], indent=2),
        "```",
        "",
        "## T3: perturbation mean versus cell-level structure",
        "",
        "A has the target KO pseudobulk mean repeated across cells. B adds a positive gene-wise offset to the KO population, changing the perturbation mean while leaving the centered KO cell cloud unchanged. Mean grafting restores A's KO mean while retaining B's cell-level structure.",
        "",
        table_for_md(numeric_frame(results["t3_response_structure"])),
        "",
        "Diagnostics:",
        "```json",
        json.dumps(results["diagnostics"]["t3_response_structure"], indent=2),
        "```",
        "",
        "## Reproduce",
        "",
        "```bash",
        "pip install -r requirements.txt",
        "python run_lab.py --out-dir results",
        "```",
        "",
    ]
    Path("RESULTS.md").write_text("\n".join(md), encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--data-dir", type=Path, default=Path(".cache/public_samples")
    )
    p.add_argument("--out-dir", type=Path, default=Path("results"))
    args = p.parse_args()

    samples = download_public_samples(args.data_dir)
    rng = np.random.default_rng(20260930)

    with tempfile.TemporaryDirectory(prefix="vec_ensemble_lab_") as tmp:
        work = Path(tmp)
        t1_ms, t1_mix, d1 = t1_mean_structure(samples, work, rng)
        t1_q, d2 = t1_quantile(samples, work, rng)
        t2, d3 = t2_spatial(samples, work, rng)
        t3, d4 = t3_response_structure(samples, work, rng)

    results = {
        "t1_mean_structure": t1_ms,
        "t1_mixture_sweep": t1_mix,
        "t1_quantile": t1_q,
        "t2_spatial": t2,
        "t3_response_structure": t3,
        "diagnostics": {
            "t1_mean_structure": d1,
            "t1_quantile": d2,
            "t2_spatial": d3,
            "t3_response_structure": d4,
        },
    }
    write_outputs(args.out_dir, results)


if __name__ == "__main__":
    main()
