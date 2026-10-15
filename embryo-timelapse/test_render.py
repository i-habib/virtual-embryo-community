"""Tests for render.py and palette.py. Run with: python -m pytest -q test_render.py"""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import palette  # noqa: E402
import render  # noqa: E402


def test_pca_frame_is_a_proper_rotation():
    for seed in range(30):
        rng = np.random.default_rng(seed)
        xyz = rng.normal(size=(300, 3)) * np.array([3.0, 2.0, 1.0]) + rng.normal(size=3) * 10
        rot, centre = render.pca_frame(xyz)
        assert np.linalg.det(rot) == pytest.approx(1.0)
        np.testing.assert_allclose(rot.T @ rot, np.eye(3), atol=1e-10)
        P = render.to_frame(xyz, rot, centre)
        # Micrometre distances are kept, so the scale is still real.
        d_in = np.linalg.norm(xyz[1:] - xyz[:-1], axis=1)
        d_out = np.linalg.norm(P[1:] - P[:-1], axis=1)
        np.testing.assert_allclose(d_out, d_in, rtol=1e-9)


def test_mirrored_cloud_still_gets_a_proper_rotation():
    # A mirrored cloud is the case where a naive SVD frame can come out with det -1.
    rng = np.random.default_rng(7)
    xyz = rng.normal(size=(500, 3)) * np.array([5.0, 3.0, 0.5])
    mirrored = xyz * np.array([-1.0, 1.0, 1.0])
    for cloud in (xyz, mirrored):
        rot, _ = render.pca_frame(cloud)
        assert np.linalg.det(rot) == pytest.approx(1.0)


def test_turntable_is_periodic_and_keeps_radius():
    rng = np.random.default_rng(3)
    P = rng.normal(size=(100, 3)) * [100.0, 60.0, 30.0]
    h0, v0, d0 = render.project(P, 0.0)
    h1, v1, d1 = render.project(P, 2 * np.pi)
    np.testing.assert_allclose(h0, h1, atol=1e-9)
    np.testing.assert_allclose(v0, v1, atol=1e-9)
    # Projection to the screen plane never stretches a distance beyond the 3D radius.
    r3 = np.linalg.norm(P, axis=1)
    h, v, d = render.project(P, 1.0)
    assert np.all(np.hypot(h, v) <= r3 + 1e-9)


def test_palette_is_deterministic_and_order_free():
    labels = ["Unknown", "V-CM", "A-CM", "Peri", "Neural Tube"]
    p1 = palette.build_palette(labels)
    p2 = palette.build_palette(list(reversed(labels)))
    p3 = palette.build_palette(labels)
    assert p1 == p2 == p3
    assert p1["Unknown"] == palette.UNKNOWN


def test_palette_is_stable_when_stages_are_reordered():
    stages = [["A-CM", "V-CM", "Unknown"], ["Peri", "A-CM"], ["Neural Tube", "V-CM"]]
    forward = palette.build_palette([x for s in stages for x in s])
    backward = palette.build_palette([x for s in reversed(stages) for x in s])
    assert forward == backward


def test_palette_gives_each_label_its_own_colour():
    labels = [f"type{i:02d}" for i in range(60)]
    table = palette.build_palette(labels)
    colours = [v for k, v in table.items() if k != "Unknown"]
    assert len(set(colours)) == len(colours)
    with pytest.raises(ValueError):
        palette.build_palette([f"x{i}" for i in range(len(palette.CANDIDATES) + 1)])


def _synthetic_h5ad(path, n=200, seed=1):
    import anndata as ad

    rng = np.random.default_rng(seed)
    xyz = rng.normal(size=(n, 3)) * [200.0, 120.0, 80.0]
    labels = rng.choice(["A-CM", "V-CM", "Peri"], n)
    X = rng.gamma(2.0, 1.0, size=(n, 5)).astype(np.float32)
    a = ad.AnnData(
        X=X,
        obs=pd.DataFrame({"celltype": pd.Categorical(labels)}, index=[f"c{i}" for i in range(n)]),
        var=pd.DataFrame(index=["Myl7", "Tnnt2", "Nkx2-5", "Gata4", "Hand2"]),
    )
    a.obsm["spatial_3D"] = xyz
    a.write_h5ad(path)
    return path


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@needs_ffmpeg
def test_synthetic_h5ad_renders_one_second_mp4(tmp_path):
    src = _synthetic_h5ad(tmp_path / "syn.h5ad")
    out = tmp_path / "syn.mp4"
    subprocess.run([sys.executable, str(HERE / "render.py"), str(src), "--out", str(out),
                    "--seconds", "1", "--fps", "10"], check=True)
    assert out.stat().st_size > 1000
    if shutil.which("ffprobe"):
        dur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(out)], capture_output=True, text=True, check=True)
        assert float(dur.stdout) == pytest.approx(1.0, abs=0.15)


@needs_ffmpeg
def test_synthetic_compare_and_gene_modes(tmp_path):
    src = _synthetic_h5ad(tmp_path / "a.h5ad", seed=1)
    ref = _synthetic_h5ad(tmp_path / "b.h5ad", seed=2)
    pair = tmp_path / "pair.mp4"
    gene = tmp_path / "gene.mp4"
    render.main([str(src), "--compare", str(ref), "--out", str(pair), "--seconds", "0.5", "--fps", "10"])
    render.main([str(src), "--color", "Tnnt2", "--out", str(gene), "--seconds", "0.5", "--fps", "10"])
    assert pair.stat().st_size > 1000
    assert gene.stat().st_size > 1000


def test_frame_scale_fills_80_percent_of_height():
    cv = render.Canvas(1280, 720)
    radii = [120.0, 350.0, 280.0]
    s = render.frame_scale(cv, radii)
    # The largest cloud's 99.5% radius, drawn at scale s, spans 80% of the frame height.
    assert 2 * max(radii) * s == pytest.approx(0.8 * 720)
    assert render.frame_scale(render.Canvas(640, 360), radii) == pytest.approx(s / 2)


def test_stage_manifest_has_validation_and_test_targets():
    import json
    entries = json.loads((HERE / "stages.json").read_text())["stages"]
    kinds = [e["kind"] for e in entries]
    assert kinds.count("released") == 6
    assert kinds.count("validation") == 3
    assert kinds.count("test") == 2
    order = [e["stage"] for e in entries]
    assert order.index("E7.5") < order.index("E7.75") < order.index("E8.0")
    assert order.index("E10.5") < order.index("E12.5")
