#!/usr/bin/env python
"""Build the released-stage timelapse: timelapse.mp4, timelapse.gif and stages.png.

Stage order, labels and held-out targets come from stages.json. Each released
stage gets a turntable. Each held-out validation or test target gets a plain card
in its place in the order. Stages of one setting share one camera scale, set so
the largest stage of that setting spans 80% of the frame height.

Usage:
  python timelapse.py --data-dir DIR [--stage-cache DIR] [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from render import (Canvas, Colours, PanelSpec, Scene, Video, frame_scale, legend_items,
                    load_stage, load_timeline, radius99, resolve_stage_path, stage_rgba)

HERE = Path(__file__).resolve().parent
SETTING_TEXT = {"embryo": "whole embryo", "heart": "heart setting"}
KIND_SUFFIX = {"validation": "validation", "test": "final test"}
HEART_NOTE = ("Heart-setting files are crops around the heart; their size reflects "
              "the dissection, not growth.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--data-dir", required=True, type=Path,
                    help="folder with E8.75.h5ad and E9.5.h5ad")
    ap.add_argument("--stage-cache", type=Path, default=None,
                    help="folder with the other released stages (default: DATA_DIR/.stage_cache)")
    ap.add_argument("--stages", type=Path, default=HERE / "stages.json")
    ap.add_argument("--palette", type=Path, default=HERE / "palette.json")
    ap.add_argument("--out-dir", type=Path, default=HERE)
    ap.add_argument("--cells", type=int, default=15000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--intro-seconds", type=float, default=3.0)
    ap.add_argument("--stage-seconds", type=float, default=5.0)
    ap.add_argument("--card-seconds", type=float, default=2.0)
    ap.add_argument("--gif-width", type=int, default=480)
    ap.add_argument("--gif-fps", type=int, default=10)
    args = ap.parse_args(argv)

    timeline = load_timeline(args.stages)
    stage_cache = args.stage_cache or args.data_dir / ".stage_cache"
    cv = Canvas(1280, 720)
    colours = Colours(args.palette)
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    # 1. Load every released stage (one at a time, subsampled, read-only).
    loaded = {}
    for e in timeline:
        if e["kind"] == "released":
            path = resolve_stage_path(e, args.data_dir, stage_cache)
            print(f"loading {e['stage']} from {path.name}", flush=True)
            loaded[e["stage"]] = load_stage(path, args.cells, args.seed, name=e["stage"])

    # 2. One camera scale per setting: the largest 99.5% radius among its released stages
    #    spans 80% of the frame height.
    radii: dict[str, list[float]] = defaultdict(list)
    for e in timeline:
        if e["kind"] == "released":
            radii[e["setting"]].append(radius99(loaded[e["stage"]].P))
    scale = {s: frame_scale(cv, r) for s, r in radii.items()}

    def stage_title(e, st):
        return f"{e['stage']} · {SETTING_TEXT[e['setting']]} · {st.n_total:,} cells · released"

    def stage_subtitle(st):
        if len(st.xyz) < st.n_total:
            return f"{len(st.xyz):,} of {st.n_total:,} cells shown (random subsample, seed {args.seed})"
        return f"all {st.n_total:,} cells shown"

    def card_title(e):
        return f"{e['stage']} · held out · {e['label']} ({KIND_SUFFIX[e['kind']]})"

    def note_for(e):
        return HEART_NOTE if e["setting"] == "heart" else None

    def stage_scene(e):
        st = loaded[e["stage"]]
        legend, more = legend_items(st.counts, colours)
        return Scene(cv, [PanelSpec(st, stage_title(e, st), stage_subtitle(st),
                                    stage_rgba(st, colours))],
                     scale[e["setting"]], legend=legend, more=more, note=note_for(e))

    def card_scene(e):
        return Scene(cv, [PanelSpec(None, card_title(e), e["subtitle"])],
                     scale[e["setting"]], note=note_for(e))

    # 3. The video: intro card, then the timeline in developmental order.
    intro = Scene(cv, [PanelSpec(
        None,
        "Virtual Embryo Challenge · 3D MERFISH stages in developmental order",
        "Released stages rotate about their first principal axis. "
        "Cards without points mark the held-out validation and test targets.")],
        1.0, scale_bar=False)
    segments = [(intro, args.intro_seconds)]
    for e in timeline:
        if e["kind"] == "released":
            segments.append((stage_scene(e), args.stage_seconds))
        else:
            segments.append((card_scene(e), args.card_seconds))

    mp4 = out / "timelapse.mp4"
    video = Video(mp4, args.fps, cv.w, cv.h)
    total = 0
    try:
        for scene, seconds in segments:
            n = max(1, round(seconds * args.fps))
            for i in range(n):
                video.write(scene.render(2.0 * np.pi * i / n))
            total += n
    finally:
        video.close()
    print(f"wrote {mp4} ({total} frames, {total / args.fps:.1f} s)", flush=True)

    # 4. Small GIF preview, cut from the MP4 so the two match.
    gif = out / "timelapse.gif"
    write_gif(mp4, gif, args.gif_width, args.gif_fps)
    print(f"wrote {gif}", flush=True)

    # 5. stages.png: two rows (embryo, heart), same camera rule as the video.
    tile = Canvas(480, 270)
    tile_scale = {s: frame_scale(tile, r) for s, r in radii.items()}
    write_strip(timeline, loaded, colours, tile, tile_scale, out)


def write_gif(mp4: Path, gif: Path, width: int, fps: int) -> None:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise SystemExit("ffmpeg not found on PATH")
    vf = (f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
          "[a]palettegen=max_colors=96:stats_mode=full[p];"
          "[b][p]paletteuse=dither=bayer:bayer_scale=3")
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4),
                    "-vf", vf, "-loop", "0", str(gif)], check=True)


def write_strip(timeline, loaded, colours, tile_cv, tile_scale, out: Path) -> None:
    """Two rows of stills: embryo setting on top, heart setting below. Held-out panels are grey."""
    W, H = 1800, 620
    cell_w, tile_w, tile_h = 300, 288, 162
    fig = Figure(figsize=(W / 100, H / 100), dpi=100, facecolor="white")
    FigureCanvasAgg(fig)

    def px_axes(x, y_top, w, h):
        return fig.add_axes([x / W, 1 - (y_top + h) / H, w / W, h / H])

    rows = [("embryo", 20), ("heart", 320)]
    for setting, top in rows:
        entries = [e for e in timeline if e["setting"] == setting]
        row_label = {"embryo": "embryo setting (whole embryo)", "heart": "heart setting"}[setting]
        fig.text(8 / W, 1 - top / H, row_label, ha="left", va="top", fontsize=13, color="#1f1f1f")
        for i, e in enumerate(entries):
            x = i * cell_w + 8
            ax = px_axes(x, top + 70, tile_w, tile_h)
            ax.set_axis_off()
            if e["kind"] == "released":
                st = loaded[e["stage"]]
                scene = Scene(tile_cv, [PanelSpec(st, "", "", stage_rgba(st, colours))],
                              tile_scale[setting], scale_bar=False)
                ax.imshow(scene.render(0.5))
                top_line = e["stage"]
                sub_line = f"{SETTING_TEXT[setting]} · {st.n_total:,} cells"
            else:
                ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                                       facecolor="#ececec", edgecolor="none"))
                top_line = f"{e['stage']}  held out"
                sub_line = f"{e['label']} ({KIND_SUFFIX[e['kind']]})"
            fig.text((x) / W, 1 - (top + 28) / H, top_line, ha="left", va="top",
                     fontsize=15, color="#1f1f1f")
            fig.text((x) / W, 1 - (top + 50) / H, sub_line, ha="left", va="top",
                     fontsize=9.5, color="#666666")
    path = out / "stages.png"
    fig.savefig(path, dpi=100, facecolor="white")
    print(f"wrote {path}", flush=True)


if __name__ == "__main__":
    main()
