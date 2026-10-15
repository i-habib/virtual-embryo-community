#!/usr/bin/env python3
"""Render the six metric videos and summary.png from the outputs of compute.py.

Inputs : responses.csv, run_info.json, anchors_T2_heart_val_interp.json and cache/ (written by compute.py)
Outputs: videos/<clip>.mp4 (1280x720, 30 fps, H.264, yuv420p, 9 s) and summary.png

Each computed step is drawn once as a still frame. Frames are held, then cross-faded to the next step, so
the video only ever shows computed points. Needs numpy and matplotlib. ffmpeg does the encoding.

    python render.py [--ffmpeg ffmpeg]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgb  # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
BOARD = "T2:heart:val_interp"
W, H, DPI, FPS = 1280, 720, 100, 30
TOTAL_FRAMES = 270           # 9 s
INTRO = 18                   # 0.6 s on the first step before anything moves
CROSS = 8                    # frames of cross-fade between computed steps

INK, MUTED, HAIR, SKILL, GHOST = "#1f1f1f", "#666666", "#cfcfcf", "#3b6ea5", "#d0d0d0"
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "Liberation Sans", "DejaVu Sans"],
    "text.color": INK,
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
})

VIDEO_CLIPS = ["scale", "stretch", "crop", "rotate", "shuffle", "jitter"]
CONTROL_CLIPS = ["crop_random_control"]

CLIP_INFO = {
    "scale": dict(title="Scale", sub="Isotropic scale of the truth coordinates about the centroid",
                  unit="scale factor", xscale=1.0, fmt=lambda v: f"scale {v:.2f} x truth"),
    "stretch": dict(title="Stretch", sub="Stretch along the long axis, volume kept",
                    unit="stretch factor", xscale=1.0,
                    fmt=lambda v: f"stretch {v:.2f} along the long axis, {v ** -0.5:.2f} across"),
    "crop": dict(title="Crop", sub="A slab is removed from one end of the cloud",
                 unit="% of cells removed", xscale=100.0,
                 fmt=lambda v: f"{100 * v:.0f}% of cells removed"),
    "rotate": dict(title="Rotate", sub="Proper rotation about the long axis (no mirroring)",
                   unit="rotation, degrees", xscale=1.0, fmt=lambda v: f"rotation {v:.0f} degrees"),
    "shuffle": dict(title="Shuffle", sub="Expression swapped between cells within a growing radius",
                    unit="swap radius, % of diameter (square-root scale)", xscale=100.0, sqrt_x=True,
                    fmt=lambda v: f"swap radius {100 * v:.0f}% of the cloud diameter"),
    "jitter": dict(title="Jitter", sub="Gaussian noise added to every cell position",
                   unit="noise sd, um", xscale=1.0, fmt=lambda v: f"position noise sd {v:.0f} um"),
    "crop_random_control": dict(title="Control: random thinning",
                                sub="Same share of cells removed at random (not a video)",
                                unit="% of cells removed", xscale=100.0,
                                fmt=lambda v: f"{100 * v:.0f}% of cells removed at random"),
}


def load_helper():
    spec = importlib.util.spec_from_file_location("vec_metric_lens", str(HERE.parent / "metric-lens" / "vec_metric_lens.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_board(helper):
    index = json.loads((CACHE / "index.json").read_text())
    return helper.anchored_board(index, BOARD)


def load_responses(path: Path):
    """clip -> metric -> list of (strength, value, skill_0_100 or None, points or None), in step order."""
    out: dict = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            skill = float(r["skill"]) if r["skill"] else None
            pts = float(r["points"]) if r["points"] else None
            out.setdefault(r["clip"], {}).setdefault(r["metric"], []).append(
                (float(r["strength"]), float(r["value"]), skill, pts))
    return out


def palette_colours(names):
    p = HERE.parent / "embryo-timelapse" / "palette.json"
    base = json.loads(p.read_text()) if p.exists() else {}
    fallback = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1",
                "#FF9DA7", "#9C755F", "#BAB0AC"]
    cols, j = {}, 0
    for n in names:
        if n in base:
            cols[n] = to_rgb(base[n])
        else:
            cols[n] = to_rgb(fallback[j % len(fallback)])
            j += 1
    return cols, ("embryo-timelapse/palette.json" if base else "fallback muted colours")


def draw_curve(ax, ax2, xs, ys, skills, k, xlim, ylim, floor, ceil, skill_axis, sqrt_x=False):
    """Metric line and optional skill line for computed steps 0..k (inclusive)."""
    if sqrt_x:
        # Square-root x axis, so the early part of the shuffle ramp is not squeezed against the left edge.
        ax.set_xscale("function", functions=(lambda x: np.sqrt(np.clip(x, 0, None)), np.square))
        ax.set_xticks([0, 5, 10, 25, 50, 100])
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(HAIR)
        ax.spines[side].set_linewidth(0.7)
    ax.tick_params(labelsize=7.5, length=2.5, color=HAIR, pad=2)
    if floor is not None:
        ax.axhline(floor, color=HAIR, lw=0.8, ls=(0, (2, 2)), zorder=0)
    if ceil is not None:
        ax.axhline(ceil, color=HAIR, lw=0.8, ls=(0, (2, 2)), zorder=0)
    ax.plot(xs[: k + 1], ys[: k + 1], color=INK, lw=1.4, marker="o", ms=2.2, mew=0, zorder=3)
    if k is not None and k < len(xs):
        ax.plot([xs[k]], [ys[k]], "o", color=INK, ms=4.2, zorder=4)
    if skill_axis:
        ax2.set_ylim(0, 100)
        ax2.set_yticks([0, 50, 100])
        ax2.tick_params(labelsize=7, length=0, colors=MUTED, pad=2)
        for side in ("top", "left", "bottom"):
            ax2.spines[side].set_visible(False)
        ax2.spines["right"].set_color(HAIR)
        ax2.spines["right"].set_linewidth(0.7)
        ax2.plot(xs[: k + 1], skills[: k + 1], color=SKILL, lw=1.2, zorder=2)
        if k is not None and k < len(xs):
            ax2.plot([xs[k]], [skills[k]], "o", color=SKILL, ms=3.6, zorder=4)


def y_limits(values, floor, ceil, skill_axis):
    pool = list(values) + [v for v in (floor, ceil) if v is not None]
    lo, hi = min(pool), max(pool)
    if hi - lo < 1e-12:
        hi = lo + 1.0
    pad = 0.08 * (hi - lo)
    if not skill_axis and floor is None:
        return (0.0, hi * 1.15)
    return (lo - pad, hi + pad)


def metric_frame(clip, k, steps, geo, board, data, colours, cols_table):
    """Draw one computed step (k) as an RGB array of shape H x W x 3."""
    info = CLIP_INFO[clip]
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor="white")
    st = steps[k]
    C = st["C"]
    codes = st["codes"]

    # left: prediction over truth ghost, same camera for every frame
    ax3 = fig.add_axes([0.0, 0.0, 0.53, 1.0], projection="3d")
    ax3.set_axis_off()
    ax3.set_proj_type("ortho")
    ax3.view_init(elev=22, azim=-62)
    cx, cy, cz, R = geo["centre"][0], geo["centre"][1], geo["centre"][2], geo["R"]
    ax3.set_xlim(cx - R, cx + R)
    ax3.set_ylim(cy - R, cy + R)
    ax3.set_zlim(cz - R, cz + R)
    ax3.set_box_aspect((1, 1, 1))
    G = data["truth_C"]
    ax3.scatter(G[:, 0], G[:, 1], G[:, 2], s=1.6, c=GHOST, depthshade=False, linewidths=0)
    ax3.scatter(C[:, 0], C[:, 1], C[:, 2], s=3.2, c=cols_table[codes], depthshade=False, linewidths=0)
    fig.text(0.02, 0.955, "Prediction, coloured by cell type", size=11, color=INK)
    fig.text(0.02, 0.925, "grey: truth", size=10, color=MUTED)
    if clip == "shuffle":
        fig.text(0.02, 0.895, "colour follows the expression each point now carries", size=9.5, color=MUTED)

    # right: header and readout
    X0, WR = 0.585, 0.375
    fig.text(X0, 0.945, info["title"], size=16, color=INK)
    fig.text(X0, 0.905, info["sub"], size=9.5, color=MUTED)
    fig.text(X0, 0.862, info["fmt"](st["strength"]), size=12, color=INK)
    y = 0.822
    for m, spec in st["metrics"].items():
        val, skill, pts, maxp = spec["value"], spec["skill"], spec["points"], spec["maxp"]
        if skill is None:
            line = f"{m}   {val:.4g}   no skill: not on the heart board"
        else:
            line = f"{m}   {val:.4g}   skill {skill:.0f}   {pts:.1f} of {maxp:.1f} points"
        fig.text(X0, y, line, size=10.5, color=INK)
        y -= 0.034
    extra = st.get("extra_line")
    if extra:
        fig.text(X0, y, extra, size=10, color=MUTED)
        y -= 0.034

    # right: one panel per metric, stacked
    names = list(st["metrics"].keys())
    top, bottom = y - 0.035, 0.085
    slot = (top - bottom) / len(names)
    for i, m in enumerate(names):
        series = geo["series"][m]
        y_top = top - i * slot
        h = slot * 0.62
        ax = fig.add_axes([X0 + 0.045, y_top - 0.035 - h, WR - 0.09, h])
        skill_axis = series["skill"] is not None
        ax2 = ax.twinx() if skill_axis else None
        draw_curve(ax, ax2, series["x"], series["y"], series["skill"] if skill_axis else None,
                   k, series["xlim"], series["ylim"], series["floor"], series["ceil"], skill_axis,
                   sqrt_x=info.get("sqrt_x", False))
        if series["floor"] is not None:
            label = f"{m}   floor {series['floor']:.4g}   ceiling {series['ceil']:.4g}"
        else:
            label = f"{m}   no board anchor"
        fig.text(X0, y_top - 0.004, label, size=8.5, color=MUTED)
        if i == len(names) - 1:
            ax.set_xlabel(info["unit"], size=8.5, labelpad=2)
    fig.text(X0, 0.035, "black: metric.   blue: skill 0 to 100, right axis.   dotted: board floor and ceiling",
             size=7.5, color=MUTED)

    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    if img.shape != (H, W, 3):
        raise RuntimeError(f"frame is {img.shape}, expected {(H, W, 3)}")
    return img


def build_clip_geometry(clip, steps_npz, truth_C, metric_series):
    """One camera per clip: centre on the truth, half-width covers 99.8% of cells in every step."""
    allc = [truth_C] + [s["C"] for s in steps_npz]
    centre = truth_C.mean(0)
    radii = np.concatenate([np.linalg.norm(c - centre, axis=1) for c in allc])
    R = float(np.percentile(radii, 99.8)) * 1.05
    return {"centre": centre, "R": R, "series": metric_series}


def timeline(n_steps):
    """Frame index lists: (step, kind) with kind 'hold' or 'fade' (alpha to next step)."""
    per = (TOTAL_FRAMES - INTRO) // (n_steps - 1)
    rest = TOTAL_FRAMES - INTRO - per * (n_steps - 1)
    frames = [(0, None)] * INTRO
    for k in range(1, n_steps):
        for j in range(CROSS):
            frames.append((k - 1, (k, (j + 1) / (CROSS + 1))))
        frames += [(k, None)] * (per - CROSS)
    frames += [(n_steps - 1, None)] * rest
    assert len(frames) == TOTAL_FRAMES
    return frames


def write_video(clip, imgs, out_path: Path, ffmpeg: str):
    tl = timeline(len(imgs))
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an",
           "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k, fade in tl:
        if fade is None:
            frame = imgs[k]
        else:
            nxt, t = fade
            frame = np.rint(imgs[k].astype(np.float32) * (1 - t) + imgs[nxt].astype(np.float32) * t).astype(np.uint8)
        proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {clip}")


def load_steps(clip, n, names_all, truth_codes_names):
    """Return per-step dicts with C, codes, strength and (later) metric info."""
    steps = []
    for i in range(n):
        z = np.load(CACHE / f"{clip}_{i:02d}.npz")
        j = json.loads((CACHE / f"{clip}_{i:02d}.json").read_text())
        steps.append({"C": z["C"].astype(np.float64), "codes": z["ct"].astype(np.int64),
                      "strength": float(j["value"]), "extra": j["extra"], "n_pred": j["n_pred"]})
    return steps


def metric_series_for(clip, rows, board):
    """x, y, skill arrays and axis limits for each metric of one clip."""
    info = CLIP_INFO[clip]
    out = {}
    for m, pts in rows.items():
        xs = np.array([p[0] for p in pts]) * info["xscale"]
        ys = np.array([p[1] for p in pts])
        skill = None
        if pts[0][2] is not None:
            skill = np.array([p[2] for p in pts])
        spec = board["metrics"].get(m)
        floor = ceil = None
        if spec is not None:
            floor, ceil = spec["floor"], spec["ceiling"]
        ylim = y_limits(ys, floor, ceil, skill is not None)
        pad = 0.03 * (xs.max() - xs.min() if xs.max() > xs.min() else 1.0)
        out[m] = {"x": xs, "y": ys, "skill": skill, "floor": floor, "ceil": ceil,
                  "xlim": (xs.min() - pad, xs.max() + pad), "ylim": ylim,
                  "max_points": None if spec is None else 100.0 * spec["weight"]}
    return out


def draw_summary(responses, board, out_path: Path):
    curves = [(c, m) for c in VIDEO_CLIPS + CONTROL_CLIPS for m in responses[c]]
    ncol = 6
    nrow = int(np.ceil(len(curves) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(18, 3.0 * nrow), facecolor="white")
    axes = np.atleast_1d(axes).ravel()
    for ax in axes:
        ax.set_axis_off()
    for ax, (clip, m) in zip(axes, curves):
        ser = metric_series_for(clip, {m: responses[clip][m]}, board)[m]
        ax.set_axis_on()
        ax2 = ax.twinx() if ser["skill"] is not None else None
        draw_curve(ax, ax2, ser["x"], ser["y"], ser["skill"], len(ser["x"]) - 1, ser["xlim"], ser["ylim"],
                   ser["floor"], ser["ceil"], ser["skill"] is not None,
                   sqrt_x=CLIP_INFO[clip].get("sqrt_x", False))
        title = f"{CLIP_INFO[clip]['title'].replace('Control: ', 'control, ')} / {m}"
        if m == "sliced_wasserstein":
            title += " (values near 1e-8 are float32 rounding)"
        ax.set_title(title, fontsize=9, loc="left", color=INK)
        ax.set_xlabel(CLIP_INFO[clip]["unit"], fontsize=8, labelpad=2)
    fig.suptitle("Each panel: one perturbation family and one metric, computed at every step. "
                 "Blue: skill 0 to 100 on the heart validation board (right axis). Dotted: board floor and ceiling.",
                 fontsize=10, color=MUTED, x=0.01, ha="left", y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out_path, dpi=DPI, facecolor="white")
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ffmpeg", default=None, help="ffmpeg binary (default: on PATH, else /opt/homebrew/bin/ffmpeg)")
    ap.add_argument("--only", default=None, help="comma-separated clips to render, for quick checks")
    args = ap.parse_args(argv)
    ffmpeg = args.ffmpeg or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not Path(ffmpeg).exists() and shutil.which(ffmpeg) is None:
        sys.exit(f"ffmpeg not found: {ffmpeg}")

    helper = load_helper()
    board = load_board(helper)
    responses = load_responses(HERE / "responses.csv")
    truth = np.load(CACHE / "truth.npz")
    truth_C = truth["C"].astype(np.float64)
    names = [str(x) for x in truth["names"]]
    colours, pal_src = palette_colours(names)
    cols_table = np.array([colours[n] for n in names])
    print(f"[render] colours: {pal_src}", flush=True)

    videos = (args.only.split(",") if args.only else VIDEO_CLIPS)
    (HERE / "videos").mkdir(exist_ok=True)
    for clip in videos:
        rows = responses[clip]
        n = len(next(iter(rows.values())))
        steps = load_steps(clip, n, names, names)
        series = metric_series_for(clip, rows, board)
        geo = build_clip_geometry(clip, steps, truth_C, series)
        data = {"truth_C": truth_C}
        names_m = list(rows.keys())
        for k, st in enumerate(steps):
            st["metrics"] = {}
            for m in names_m:
                _, v, sk, pts = rows[m][k]
                maxp = series[m]["max_points"]
                st["metrics"][m] = {"value": v, "skill": sk, "points": pts,
                                    "maxp": maxp if maxp is not None else 0.0}
            ex = st["extra"]
            if clip == "rotate":
                st["extra_line"] = "values near 1e-8 are float32 rounding after rotation, not geometry"
            elif "frac_moved" in ex:
                st["extra_line"] = f"cells with swapped expression: {100 * ex['frac_moved']:.0f}%"
            elif "cells_kept" in ex:
                st["extra_line"] = f"cells kept: {ex['cells_kept']} of {len(truth_C)}"
        imgs = []
        for k in range(n):
            imgs.append(metric_frame(clip, k, steps, geo, board, data, colours, cols_table))
            print(f"[render] {clip} frame-still {k + 1}/{n}", flush=True)
        write_video(clip, imgs, HERE / "videos" / f"{clip}.mp4", ffmpeg)
        print(f"[render] wrote videos/{clip}.mp4", flush=True)

    if not args.only:
        draw_summary(responses, board, HERE / "summary.png")
        print("[render] wrote summary.png", flush=True)


if __name__ == "__main__":
    main()
