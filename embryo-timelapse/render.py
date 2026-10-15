#!/usr/bin/env python
"""Render a turntable MP4 of 3D point clouds from an AnnData (.h5ad) file.

The file needs obsm["spatial_3D"] in micrometres. Colour is obs["celltype"] with
the fixed palette from palette.py, or one gene's expression with --color GENE.
With --compare REF the two clouds are drawn side by side, with one camera and one
scale for both.

Examples:
  python render.py my_predictions.h5ad --out predictions.mp4
  python render.py my_predictions.h5ad --compare reference.h5ad --out side_by_side.mp4
  python render.py reference.h5ad --color Tnnt2 --out tnnt2.mp4
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = ["Helvetica", "Arial", "Liberation Sans", "DejaVu Sans"]

import matplotlib.colors as mcolors  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

import palette  # noqa: E402  (same folder)

HERE = Path(__file__).resolve().parent
DPI = 100
BASE_W, BASE_H = 1280, 720           # layout is drawn on this design grid, then scaled
TEXT = "#1f1f1f"
SUBTLE = "#666666"
LEGEND_TEXT = "#555555"
ALPHA = 0.8
POINT_SIZE = 2.2                     # matplotlib s (pt^2): about 2 px dots at 100 dpi
ELEVATION = np.deg2rad(15.0)         # viewer slightly above the turntable
FILL = 0.92                          # fraction of the panel half-height the cloud may use
MAX_LEGEND = 12
GENE_CMAP = mcolors.LinearSegmentedColormap.from_list("gene", ["#d9d9d9", "#1f3b73"])


# --------------------------------------------------------------------------- geometry

def pca_frame(xyz: np.ndarray):
    """Return (rot, centre). Columns of rot are the principal axes, largest first.

    det(rot) is forced to +1, so the frame is a rotation and never a reflection.
    Distances are unchanged, so the cloud stays in micrometres.
    """
    centre = xyz.mean(axis=0)
    _, _, vt = np.linalg.svd(xyz - centre, full_matrices=False)
    rot = vt.T.copy()
    if np.linalg.det(rot) < 0:
        rot[:, 2] *= -1.0
    return rot, centre


def to_frame(xyz: np.ndarray, rot: np.ndarray, centre: np.ndarray) -> np.ndarray:
    """Coordinates in the principal-axis frame, centred on the mean (micrometres)."""
    return (xyz - centre) @ rot


def project(P: np.ndarray, theta: float):
    """Turntable view. The cloud spins about its first principal axis, drawn vertical.

    Returns (horizontal, vertical, depth) in micrometres. Depth is towards the viewer.
    """
    c, s = np.cos(theta), np.sin(theta)
    up = P[:, 0]
    h = c * P[:, 1] - s * P[:, 2]
    d = s * P[:, 1] + c * P[:, 2]
    ce, se = np.cos(ELEVATION), np.sin(ELEVATION)
    v = up * ce - d * se
    depth = up * se + d * ce
    return h, v, depth


def radius99(P: np.ndarray) -> float:
    """Radius that contains 99.5% of the cells. Used to fix the shared scale."""
    return float(np.percentile(np.linalg.norm(P, axis=1), 99.5))


# --------------------------------------------------------------------------- layout

class Canvas:
    """Pixel canvas. Layout is specified on a 1280x720 grid and scaled to (w, h)."""

    def __init__(self, w: int = BASE_W, h: int = BASE_H):
        if w % 2 or h % 2:
            raise SystemExit("frame size must be even in both directions (H.264 yuv420p)")
        self.w, self.h = int(w), int(h)
        self.kx, self.ky = self.w / BASE_W, self.h / BASE_H
        self.k = min(self.kx, self.ky)

    @classmethod
    def from_size(cls, text: str) -> "Canvas":
        try:
            w, h = (int(v) for v in text.lower().split("x"))
        except ValueError as exc:
            raise SystemExit(f"--size must look like 1280x720, got {text!r}") from exc
        return cls(w, h)

    def fx(self, v: float) -> float:
        return v / BASE_W

    def fy(self, v: float) -> float:
        return 1.0 - v / BASE_H

    def pt(self, size: float) -> float:
        return size * self.k


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float


def layout_boxes(n_panels: int):
    """Panel boxes on the 1280x720 design grid (top-left origin)."""
    if n_panels <= 1:
        return [Box(40, 84, 960, 600)]
    return [Box(40, 110, 580, 490), Box(660, 110, 580, 490)]


def scale_for(cv: Canvas, n_panels: int, radii) -> float:
    """Pixels per micrometre that fits the cloud in its panel box (used by render.py)."""
    box = layout_boxes(n_panels)[0]
    return FILL * min(box.w * cv.kx, box.h * cv.ky) / 2.0 / max(radii)


def frame_scale(cv: Canvas, radii, frac: float = 0.8) -> float:
    """Pixels per micrometre so the largest cloud (99.5% radius) spans `frac` of the frame height."""
    return frac * cv.h / 2.0 / max(radii)


# --------------------------------------------------------------------------- data

@dataclass
class Stage:
    name: str
    xyz: np.ndarray                  # (n, 3) shown cells, micrometres
    P: np.ndarray                    # principal-axis frame of xyz
    n_total: int                     # cells in the file
    labels: np.ndarray | None = None  # cell-type string per shown cell
    counts: pd.Series | None = None  # cell-type counts over the whole file
    values: np.ndarray | None = None  # gene values per shown cell (gene mode)
    gene: str | None = None
    log1p_applied: bool = False


def load_stage(path, cells=15000, seed=0, gene=None, name=None,
               coord_key="spatial_3D", label_key="celltype") -> Stage:
    """Read obs and obsm (and one gene column) from a file. Subsample with a fixed seed."""
    import anndata as ad

    path = Path(path)
    a = ad.read_h5ad(path, backed="r")
    try:
        if coord_key not in a.obsm.keys():
            raise SystemExit(f"{path.name}: no obsm['{coord_key}'] (needed for 3D rendering)")
        n = int(a.n_obs)
        rng = np.random.default_rng(seed)
        idx = np.sort(rng.choice(n, size=min(cells, n), replace=False))

        xyz_all = np.asarray(a.obsm[coord_key][:], dtype=np.float64)[:, :3]
        keep = np.isfinite(xyz_all[idx]).all(axis=1)
        idx = idx[keep]
        xyz = xyz_all[idx]

        labels = counts = None
        if label_key in a.obs.columns:
            full = a.obs[label_key].astype(str).to_numpy()
            counts = pd.Series(full).value_counts()
            labels = full[idx]

        values = None
        log1p_applied = False
        if gene is not None:
            if gene not in a.var_names:
                raise SystemExit(f"{path.name}: gene {gene!r} is not in var_names")
            col = a.X[:, a.var_names.get_loc(gene)]
            col = col.toarray() if sp.issparse(col) else np.asarray(col)
            values = np.asarray(col, dtype=np.float64).ravel()[idx]
            # Released files hold log-normalised .X. Raw integer counts get log1p here.
            if values.size and values.max() > 30 and np.allclose(values, np.round(values)):
                values = np.log1p(values)
                log1p_applied = True
    finally:
        a.file.close()

    rot, centre = pca_frame(xyz)
    return Stage(
        name=name or path.stem, xyz=xyz, P=to_frame(xyz, rot, centre), n_total=n,
        labels=labels, counts=counts, values=values, gene=gene, log1p_applied=log1p_applied,
    )


def resolve_stage_path(entry: dict, data_dir: Path, stage_cache: Path) -> Path:
    base = stage_cache if entry.get("location") == "stage_cache" else data_dir
    path = Path(base) / entry["file"]
    if not path.exists():
        raise SystemExit(f"missing {entry['stage']} file: {path}")
    return path


def load_timeline(path) -> list[dict]:
    return json.loads(Path(path).read_text())["stages"]


class Colours:
    """Label -> hex colour from palette.json. Unknown labels get a hashed fallback colour."""

    def __init__(self, path=None):
        self.table: dict[str, str] = {}
        if path and Path(path).exists():
            self.table = json.loads(Path(path).read_text())
        self._warned: set[str] = set()

    def hex(self, label: str) -> str:
        if label in self.table:
            return self.table[label]
        if label not in self._warned:
            self._warned.add(label)
            print(f"note: {label!r} is not in palette.json; using a hashed colour", file=sys.stderr)
        return palette.fallback_colour(label)


def stage_rgba(stage: Stage, colours: Colours, vmax: float | None = None) -> np.ndarray:
    n = len(stage.xyz)
    if stage.gene is not None:
        x = np.clip(stage.values / vmax, 0.0, 1.0)
        rgba = GENE_CMAP(x)
        rgba[:, 3] = ALPHA
        return rgba
    if stage.labels is None:
        return np.tile(np.asarray(mcolors.to_rgba("#4E79A7", ALPHA)), (n, 1))
    uniq, inv = np.unique(stage.labels, return_inverse=True)
    lut = np.array([mcolors.to_rgba(colours.hex(u), ALPHA) for u in uniq])
    return lut[inv]


def gene_vmax(stage: Stage) -> float:
    v = float(np.percentile(stage.values, 99)) if stage.values is not None else 0.0
    return v if v > 0 else 1.0


def legend_items(counts: pd.Series, colours: Colours):
    """Top MAX_LEGEND cell types by count over the whole file, plus a 'more' note."""
    counts = counts.sort_values(ascending=False, kind="stable")
    items = [(str(lab), colours.hex(str(lab))) for lab in counts.index[:MAX_LEGEND]]
    more = len(counts) - MAX_LEGEND
    return items, (f"+ {more} more types" if more > 0 else None)


# --------------------------------------------------------------------------- drawing

@dataclass
class PanelSpec:
    stage: Stage | None
    title: str
    subtitle: str = ""
    rgba: np.ndarray | None = None


class PointPanel:
    def __init__(self, scene: "Scene", box: Box, spec: PanelSpec):
        cv = scene.cv
        self.ax = scene.fig.add_axes(
            [cv.fx(box.x), cv.fy(box.y + box.h), box.w / BASE_W, box.h / BASE_H])
        self.ax.set_axis_off()
        self.P = spec.stage.P
        self.rgba = spec.rgba
        self.sc = self.ax.scatter([], [], s=POINT_SIZE, linewidths=0)
        half_w = box.w * cv.kx / 2.0 / scene.scale
        half_h = box.h * cv.ky / 2.0 / scene.scale
        self.ax.set_xlim(-half_w, half_w)
        self.ax.set_ylim(-half_h, half_h)
        self.ax.set_autoscale_on(False)
        self.update(0.0)

    def update(self, theta: float) -> None:
        h, v, depth = project(self.P, theta)
        order = np.argsort(depth, kind="stable")          # far first, near last
        self.sc.set_offsets(np.column_stack((h[order], v[order])))
        self.sc.set_facecolor(self.rgba[order])


class Scene:
    """One figure with one card or one or two point-cloud panels, plus its text.

    `scale` is pixels per micrometre and must be the same for every panel that
    should be compared. `legend` is a list of (label, hex) pairs.
    """

    def __init__(self, cv: Canvas, panels: list[PanelSpec], scale: float = 1.0,
                 legend=None, more: str | None = None, colourbar=None, scale_bar=True,
                 note: str | None = None):
        self.cv = cv
        self.scale = scale
        self.pair = len(panels) > 1
        self.fig = Figure(figsize=(cv.w / DPI, cv.h / DPI), dpi=DPI, facecolor="white")
        FigureCanvasAgg(self.fig)
        self.points: list[PointPanel] = []
        for spec, box in zip(panels, layout_boxes(len(panels))):
            self._text(box.x, 30, spec.title, 13, TEXT)
            if spec.subtitle:
                self._text(box.x, 56, spec.subtitle, 10, SUBTLE)
            if spec.stage is not None:
                self.points.append(PointPanel(self, box, spec))
        if legend:
            self._legend(legend, more)
        if colourbar is not None:
            self._colourbar(*colourbar)
        if note:
            self._text(40, 76, note, 10, SUBTLE)
        if scale_bar:
            self._scale_bar()

    def _text(self, x, y, s, size, colour, ha="left", va="top"):
        self.fig.text(self.cv.fx(x), self.cv.fy(y), s, fontsize=self.cv.pt(size),
                      color=colour, ha=ha, va=va)

    def _legend(self, items, more):
        if self.pair:
            x0, y0, ncol, col_w = 40, 628, 6, 200
        else:
            x0, y0, ncol, col_w = 1030, 130, 1, 0
        row = 22
        for i, (label, colour) in enumerate(items):
            r, c = divmod(i, ncol)
            x, y = x0 + c * col_w, y0 + r * row
            self.fig.add_artist(Rectangle(
                (self.cv.fx(x), self.cv.fy(y + 9)), 9 / BASE_W, 9 / BASE_H,
                transform=self.fig.transFigure, facecolor=colour, edgecolor="none"))
            self._text(x + 16, y + 4.5, label, 9, LEGEND_TEXT, va="center")
        if more and not self.pair:
            r = len(items)
            self._text(x0 + 16, y0 + r * row + 4.5, more, 9, LEGEND_TEXT, va="center")

    def _colourbar(self, label, vmax):
        x, y, w = (40, 646, 300) if self.pair else (1030, 160, 200)
        self._text(x, y - 16, label, 9, LEGEND_TEXT)
        ax = self.fig.add_axes([self.cv.fx(x), self.cv.fy(y + 10), w / BASE_W, 10 / BASE_H])
        ax.imshow(np.linspace(0, 1, 256)[None, :], aspect="auto", cmap=GENE_CMAP,
                  extent=(0, 1, 0, 1))
        ax.set_axis_off()
        self._text(x, y + 14, "0", 8, LEGEND_TEXT)
        self._text(x + w, y + 14, f"{vmax:.2f}", 8, LEGEND_TEXT, ha="right")

    def _scale_bar(self):
        cv = self.cv
        length = 100.0 * self.scale / cv.kx          # design units
        x0, y0 = 40, 690
        self.fig.add_artist(Line2D(
            [cv.fx(x0), cv.fx(x0 + length)], [cv.fy(y0), cv.fy(y0)],
            transform=self.fig.transFigure, color=TEXT, linewidth=1.0, solid_capstyle="butt"))
        self._text(x0 + length + 8, y0, "100 µm", 9, TEXT, va="center")

    def render(self, theta: float) -> np.ndarray:
        for p in self.points:
            p.update(theta)
        self.fig.canvas.draw()
        buf = np.asarray(self.fig.canvas.buffer_rgba())
        return buf[:, :, :3].copy()


class Video:
    """Pipes RGB frames to ffmpeg (H.264, yuv420p, crf 23)."""

    def __init__(self, out, fps: int, w: int, h: int):
        exe = shutil.which("ffmpeg")
        if exe is None:
            raise SystemExit("ffmpeg not found on PATH (on macOS: /opt/homebrew/bin/ffmpeg)")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(out)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, frame: np.ndarray) -> None:
        self.proc.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())

    def close(self) -> None:
        self.proc.stdin.close()
        err = self.proc.stderr.read()
        if self.proc.wait() != 0:
            raise SystemExit("ffmpeg failed:\n" + err.decode(errors="replace"))


# --------------------------------------------------------------------------- CLI

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("file", type=Path, help=".h5ad with obsm['spatial_3D'] (micrometres)")
    ap.add_argument("--out", required=True, type=Path, help="output .mp4")
    ap.add_argument("--compare", type=Path, default=None,
                    help="reference .h5ad, drawn on the right with the same camera and scale")
    ap.add_argument("--color", default="celltype",
                    help="'celltype' (default) or a gene name in var_names")
    ap.add_argument("--cells", type=int, default=15000, help="subsample to at most this many cells")
    ap.add_argument("--seconds", type=float, default=6.0, help="length of one full turn")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", default="1280x720", help="WxH, both even")
    ap.add_argument("--seed", type=int, default=0, help="subsampling seed")
    ap.add_argument("--palette", type=Path, default=HERE / "palette.json")
    args = ap.parse_args(argv)

    cv = Canvas.from_size(args.size)
    gene = None if args.color == "celltype" else args.color
    files = [args.file] + ([args.compare] if args.compare else [])
    stages = [load_stage(f, args.cells, args.seed, gene=gene) for f in files]

    colours = Colours(args.palette)
    vmax = max(gene_vmax(s) for s in stages) if gene else None
    scale = scale_for(cv, len(stages), [radius99(s.P) for s in stages])

    panels = []
    for s in stages:
        shown = f"{len(s.xyz):,} of {s.n_total:,} cells shown" if len(s.xyz) < s.n_total \
            else f"all {s.n_total:,} cells shown"
        if gene:
            extra = " (log1p applied)" if s.log1p_applied else ""
            sub = f"colour: {gene}, log-normalised{extra} · {shown}"
        else:
            sub = f"colour: cell type · {shown}"
        panels.append(PanelSpec(stage=s, title=f"{s.name} · {s.n_total:,} cells", subtitle=sub,
                                rgba=stage_rgba(s, colours, vmax)))

    legend = more = colourbar = None
    if gene:
        colourbar = (f"{gene}, log1p expression", vmax)
    elif all(s.counts is not None for s in stages):
        counts = pd.concat([s.counts for s in stages]).groupby(level=0).sum()
        legend, more = legend_items(counts, colours)

    scene = Scene(cv, panels, scale, legend=legend, more=more, colourbar=colourbar)
    n_frames = max(1, round(args.seconds * args.fps))
    video = Video(args.out, args.fps, cv.w, cv.h)
    try:
        for i in range(n_frames):
            video.write(scene.render(2.0 * np.pi * i / n_frames))
    finally:
        video.close()
    print(f"wrote {args.out} ({n_frames} frames at {args.fps} fps)")


if __name__ == "__main__":
    main()
