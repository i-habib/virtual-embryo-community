#!/usr/bin/env python
"""Fixed cell-type colours shared by every stage and every video.

The palette is built from the union of obs["celltype"] over the released stages
listed in stages.json. Sorted label strings take colours from a fixed list in
order, so the same label string always gets the same colour and the result does
not depend on the order of the stages. "Unknown" is always grey.

Usage:
  python palette.py --data-dir DIR [--stage-cache DIR] [--out palette.json]
"""
from __future__ import annotations

import argparse
import colorsys
import json
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Okabe-Ito (black dropped) followed by muted, tab10/tab20-like tones.
BASE = [
    "#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7",
    "#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#76B7B2", "#EDC948", "#B07AA1",
    "#FF9DA7", "#9C755F", "#6F8FAF", "#A0CBE8", "#FFBE7D", "#8CD17D", "#D37295",
    "#499894", "#86BCB6", "#D4A6C8", "#B6992D", "#7A6F6B", "#5C4B8A",
]
UNKNOWN = "#BDBDBD"


def _shift(hex_colour: str, dlightness: float) -> str:
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = min(0.9, max(0.15, l + dlightness))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02X}{:02X}{:02X}".format(*(round(c * 255) for c in (r, g, b)))


# 27 base hues, then the same hues lighter and darker. The released stages hold
# 66 distinct labels, so the lighter and darker variants are needed.
CANDIDATES = BASE + [_shift(c, +0.14) for c in BASE] + [_shift(c, -0.14) for c in BASE]


def build_palette(labels) -> dict:
    """Map each label string to a hex colour. Input order does not matter."""
    names = sorted({str(x) for x in labels} - {"Unknown"})
    if len(names) > len(CANDIDATES):
        raise ValueError(f"{len(names)} labels but only {len(CANDIDATES)} colours; extend CANDIDATES")
    table = {name: CANDIDATES[i] for i, name in enumerate(names)}
    table["Unknown"] = UNKNOWN
    return dict(sorted(table.items()))


def fallback_colour(label: str) -> str:
    """Colour for a label that is not in palette.json (e.g. a user's own file)."""
    return BASE[zlib.crc32(label.encode("utf-8")) % len(BASE)]


def main(argv=None) -> None:
    from render import load_timeline, resolve_stage_path

    ap = argparse.ArgumentParser(description="Build palette.json from the released stages.")
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--stage-cache", type=Path, default=None,
                    help="default: DATA_DIR/.stage_cache")
    ap.add_argument("--stages", type=Path, default=HERE / "stages.json")
    ap.add_argument("--out", type=Path, default=HERE / "palette.json")
    args = ap.parse_args(argv)

    import anndata as ad

    stage_cache = args.stage_cache or args.data_dir / ".stage_cache"
    labels: set[str] = set()
    for entry in load_timeline(args.stages):
        if entry["kind"] != "released":
            continue
        path = resolve_stage_path(entry, args.data_dir, stage_cache)
        a = ad.read_h5ad(path, backed="r")
        try:
            labels |= set(a.obs["celltype"].astype(str))
        finally:
            a.file.close()

    table = build_palette(labels)
    args.out.write_text(json.dumps(table, indent=1) + "\n")
    print(f"{len(table) - 1} labels (+ Unknown) written to {args.out}")


if __name__ == "__main__":
    main()
