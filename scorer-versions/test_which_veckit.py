"""Tests for which_veckit.py using synthetic module trees and a tiny registry.

Run from this folder with the tools env:  ../../scorer-variants/envs/tools/bin/python -m pytest -q
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

import which_veckit as wv

HERE = Path(__file__).resolve().parent
MODULE_FILES = ["score_h5ad.py", "veckit.py", "common/__init__.py", "common/core_metrics.py",
                "T1/__init__.py", "T1/metrics.py", "T2/__init__.py", "T2/metrics.py"]

BASE = {
    "score_h5ad.py": "def main():\n    pass\n",
    "veckit.py": "from score_h5ad import main\n",
    "common/__init__.py": "",
    "common/core_metrics.py": "def severity_slope(x):\n    return x\n",
    "T1/__init__.py": "",
    "T1/metrics.py": "def f():\n    return 1\n",
    "T2/__init__.py": "",
    "T2/metrics.py": "def g():\n    return 2\n",
}


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hashes(files: dict[str, str]) -> dict[str, str]:
    return {rel: sha(files[rel]) for rel in MODULE_FILES}


@pytest.fixture()
def registry() -> dict:
    fixed = dict(BASE, **{"common/core_metrics.py": BASE["common/core_metrics.py"] + "# fix\n"})
    pr_variant = dict(BASE, **{"T2/metrics.py": "def g():\n    return 3\n"})
    released_text = dict(BASE, **{"common/core_metrics.py": "def severity_slope(x):\n    return x\n# severity_ratio\n"})
    return {
        "module_files": MODULE_FILES,
        "variants": {
            "rel-old": {"origin": "release old", "date": "2026-01-01", "note": "n", "issue7_fix": False,
                        "mentions_severity_ratio_or_scale_ratio": False, "module_sha256": hashes(BASE)},
            "rel-old-twin": {"origin": "release twin", "date": "2026-01-02", "note": "n", "issue7_fix": False,
                             "mentions_severity_ratio_or_scale_ratio": False, "module_sha256": hashes(BASE)},
            "rel-new": {"origin": "release new", "date": "2026-02-01", "note": "n", "issue7_fix": True,
                        "mentions_severity_ratio_or_scale_ratio": False, "module_sha256": hashes(fixed)},
            "pr-two": {"origin": "unmerged PR #2 (branch pr2)", "date": "2026-03-01", "note": "n",
                       "issue7_fix": False, "mentions_severity_ratio_or_scale_ratio": False,
                       "module_sha256": hashes(pr_variant)},
        },
    }


def test_exact_unique_release_is_identified(tmp_path, registry):
    tree = write_tree(tmp_path / "t", dict(BASE, **{"common/core_metrics.py": "def severity_slope(x):\n    return x\n# fix\n"}))
    res = wv.identify(tree, registry)
    assert res["ok"] and res["answer"] == "rel-new"
    assert res["ambiguous"] == []
    assert not any("unmerged" in w for w in res["warnings"])


def test_identical_releases_are_reported_as_ambiguous(tmp_path, registry):
    tree = write_tree(tmp_path / "t", BASE)
    res = wv.identify(tree, registry)
    assert res["ok"] and res["answer"] is None
    assert res["ambiguous"] == ["rel-old", "rel-old-twin"]


def test_unmerged_only_tree_names_the_pr_and_warns(tmp_path, registry):
    tree = write_tree(tmp_path / "t", dict(BASE, **{"T2/metrics.py": "def g():\n    return 3\n"}))
    res = wv.identify(tree, registry)
    assert res["answer"] == "pr-two"
    assert any("unmerged PR branch" in w for w in res["warnings"])
    assert any("lacks the issue #7 fix" in w for w in res["warnings"])


def test_modified_tree_is_unknown_with_closest_and_differing_files(tmp_path, registry):
    edited = dict(BASE, **{"T1/metrics.py": "def f():\n    return 99\n"})
    res = wv.identify(write_tree(tmp_path / "t", edited), registry)
    assert not res["ok"]
    assert res["closest"]["variant"] in {"rel-old", "rel-old-twin"}
    assert res["closest"]["differing_files"] == ["T1/metrics.py"]


def test_missing_and_unexpected_files_are_listed(tmp_path, registry):
    files = {k: v for k, v in BASE.items() if k != "T2/metrics.py"}
    files["T3/metrics.py"] = "x = 1\n"
    res = wv.identify(write_tree(tmp_path / "t", files), registry)
    assert res["missing_files"] == ["T2/metrics.py"]
    assert res["unexpected_files"] == ["T3/metrics.py"]
    assert not res["ok"]


def test_severity_ratio_text_triggers_board_warning(tmp_path, registry):
    files = dict(BASE, **{"common/core_metrics.py": "def severity_ratio(x):\n    return x\n"})
    res = wv.identify(write_tree(tmp_path / "t", files), registry)
    assert any("severity_ratio" in w and "does not rank" in w for w in res["warnings"])


def test_find_installed_root_uses_importlib_without_importing(tmp_path, monkeypatch):
    pkg = write_tree(tmp_path / "site", {"veckit.py": "raise RuntimeError('must not be imported')\n"})
    monkeypatch.syspath_prepend(str(pkg))
    monkeypatch.delitem(sys.modules, "veckit", raising=False)
    assert wv.find_installed_root() == pkg.resolve()
    assert "veckit" not in sys.modules


def test_cli_exit_codes(tmp_path, registry):
    import json
    reg_path = tmp_path / "variants.json"
    reg_path.write_text(json.dumps(registry), encoding="utf-8")
    tree = write_tree(tmp_path / "t", BASE)
    script = str(HERE / "which_veckit.py")
    ok = subprocess.run([sys.executable, script, "--root", str(tree), "--registry", str(reg_path)],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    edited = write_tree(tmp_path / "e", dict(BASE, **{"T1/metrics.py": "x = 2\n"}))
    unknown = subprocess.run([sys.executable, script, "--root", str(edited), "--registry", str(reg_path)],
                             capture_output=True, text=True)
    assert unknown.returncode == 1
    assert "unknown/modified" in unknown.stdout


def test_real_registry_has_one_row_per_variant_and_fixed_module_list():
    import json
    reg = json.loads((HERE / "variants.json").read_text(encoding="utf-8"))
    assert len(reg["module_files"]) == 14
    for name, v in reg["variants"].items():
        assert sorted(v["module_sha256"]) == sorted(reg["module_files"]), name
