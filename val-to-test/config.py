"""Load and validate a pseudo-pair configuration.

Stage paths may contain environment variables (for example ${VEC_STAGE_DIR}) so that no
machine-specific path is committed. A path containing PLACEHOLDER is accepted by the loader
(so templates validate) but refused by prepare.py until it is filled in.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CEILING = "__ceiling__"
DEFAULT_BOARDS = {"T1": "T1:val", "T2": "T2:heart:val_extrap", "T3": "T3:gata4"}
_UNSET = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*")


class ConfigError(ValueError):
    pass


def load_config(path) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("name", "stages", "pairs", "seeds", "subsample_cells", "subsample_seed"):
        if key not in cfg:
            raise ConfigError(f"config is missing '{key}'")
    if not cfg["seeds"] or len(set(cfg["seeds"])) != len(cfg["seeds"]):
        raise ConfigError("seeds must be a non-empty list of distinct integers")
    for sname, st in cfg["stages"].items():
        if "path" not in st or "time" not in st:
            raise ConfigError(f"stage {sname!r} needs 'path' and 'time'")
        st["time"] = float(st["time"])
    for pname, pair in cfg["pairs"].items():
        task = pair.get("task", "T2")
        if task not in DEFAULT_BOARDS:
            raise ConfigError(f"pair {pname!r}: task must be T1, T2 or T3")
        pair["task"] = task
        pair.setdefault("setting", "heart")
        pair.setdefault("board", DEFAULT_BOARDS[task])
        if not pair.get("inputs"):
            raise ConfigError(f"pair {pname!r} needs at least one input stage")
        for name in pair["inputs"] + [pair["target"]]:
            if name not in cfg["stages"]:
                raise ConfigError(f"pair {pname!r} names unknown stage {name!r}")
        pair["inputs"] = sorted(pair["inputs"], key=lambda n: cfg["stages"][n]["time"])
        t_target = cfg["stages"][pair["target"]]["time"]
        for n in pair["inputs"]:
            # T3 knockout pairs are leave-one-knockout at one stage, so equal times are allowed there.
            if task != "T3" and cfg["stages"][n]["time"] >= t_target:
                raise ConfigError(f"pair {pname!r}: input {n!r} is not earlier than the target")
        if task == "T3":
            if pair.get("wt") not in cfg["stages"]:
                raise ConfigError(f"pair {pname!r}: T3 pairs need 'wt' naming a stage")
    return cfg


def expand_path(raw: str) -> str:
    expanded = os.path.expandvars(raw)
    if _UNSET.search(expanded):
        raise ConfigError(f"unset environment variable in stage path {raw!r}")
    return expanded


def stage_source(cfg: dict, name: str) -> Path:
    """Path of the released .h5ad for a stage. Refuses placeholders."""
    raw = cfg["stages"][name]["path"]
    if "PLACEHOLDER" in raw:
        raise ConfigError(f"stage {name!r} still has a placeholder path ({raw}); fill it in first")
    return Path(expand_path(raw))


def stage_file(work: Path, name: str) -> Path:
    """Path of the subsampled stage file written by prepare.py."""
    return Path(work) / "stages" / f"{name}.h5ad"


def pair_signature(cfg: dict, pair_name: str) -> str:
    """Hash of everything that changes a score. Paths are excluded, so moving data does not invalidate the cache."""
    pair = cfg["pairs"][pair_name]
    body = {
        "stages": {n: cfg["stages"][n]["time"] for n in pair["inputs"] + [pair["target"]]},
        "inputs": pair["inputs"],
        "target": pair["target"],
        "task": pair["task"],
        "setting": pair["setting"],
        "board": pair["board"],
        "wt": pair.get("wt"),
        "subsample_cells": cfg["subsample_cells"],
        "subsample_seed": cfg["subsample_seed"],
    }
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
