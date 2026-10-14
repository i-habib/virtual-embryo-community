# Which veckit scorer am I running?

Several versions of the `veckit` scorer are in circulation for the Virtual Embryo Challenge, and they are not the same code. Two people scoring the same file can get different numbers, and nothing in the output says which version produced them. This folder identifies the versions by hashing their code, measures what the differences do to the metrics, and gives a one-command check of your own install.

It is community analysis. The organisers' scorer and pages are the source of truth, and the version the leaderboard itself runs is not published.

## The short version

- **`pip install veckit` gives you 0.1.2, which is the unmerged PR #6 branch.** Its 14 scoring modules are byte-identical to `feat/metric-hardening-0.2.0` on GitHub. It was published on 2026-08-25 and has not been updated since.
- **0.1.2 does not contain the fix for [issue #7](https://github.com/aristoteleo/veckit/issues/7)**, merged into GitHub `main` on 2026-10-02 as PR #9. Without it, some proper rotations of a correct 3D prediction lower `occupancy_dice`. On 3,000 cells of the released E9.5 MERFISH file, 5 of 12 random rotations of a perfect prediction dropped `occupancy_dice` from 1.0 to as low as 0.83. With the published anchors that drop costs up to 1.7 leaderboard points on the heart interpolation board and 3.4 on heart extrapolation, and nothing on the embryo board, where 0.83 is still above the ceiling.
- **0.1.2 reports three metrics the leaderboard does not rank**: `scale_ratio` and `size_fidelity` (Task 2) and `severity_ratio` (Task 3). Its code comments call the ratios "what ranks". The board contract ([`panels/index.json`](https://virtualembryo.ai/challenge/panels/index.json)) anchors `scale_log_ratio` and `severity_slope` instead, and the [evaluation page](https://virtualembryo.ai/challenge/evaluation?task=3&section=scoring) (Task 3 > Scoring) names `common/core_metrics.py::severity_slope`.
- **GitHub `main` (`cc3859a`) has the fix and the board's documented metric set.** It is 0.1.1 plus the issue #7 fix and nothing else.
- **Task 1 scores are the same in every version.**

## Check your install

```bash
python which_veckit.py                # the veckit importable from this interpreter
python which_veckit.py --root DIR     # an unpacked wheel or a checkout
```

It prints the matching variant, or `unknown/modified` with the files that differ, and plain warnings for the issues above. Exit code 0 for a known variant, 1 for an unknown or modified one, 2 when no veckit is found. Where several variants share identical code it lists all of them rather than picking one. Standard library only.

Example output on a `pip install veckit` environment:

```text
result: pypi-0.1.2
byte-identical scoring modules also in: pr6
WARNING: lacks the issue #7 fix (right-handed PCA frame in common/shape_metrics.py; merged into main as cc3859a): pypi-0.1.2, pr6
WARNING: scoring modules are byte-identical to an unmerged PR branch, which is not on main: pr6
WARNING: reports severity_ratio and/or scale_ratio, which the leaderboard does not rank. ...
```

To install the version that matches the documented metrics:

```bash
pip install "git+https://github.com/aristoteleo/veckit@cc3859ab2a2305efc4544815d3f44f660efa77d4"
```

Its `pyproject.toml` still says 0.1.1, so `pip show veckit` cannot tell it apart from the PyPI 0.1.1 release; `which_veckit.py` can. When you compare numbers with someone else, both run `which_veckit.py` first and quote the variant name.

## Variants

`variants.json` holds the SHA-256 of each of the 14 scoring modules (`score_h5ad.py`, `veckit.py`, `common/*.py`, `T1/*.py`, `T2/*.py`, `T3/*.py`) for 11 variants: the three PyPI releases, two commits on `main`, and the six open pull requests that touch code.

| variant | what it is | issue #7 fix | scoring code identical to |
|---|---|---|---|
| `pypi-0.1.0` | PyPI, 2026-08-10 | no | `pypi-0.1.1`, `git-46d41e6`, `pr4`, `pr5` |
| `pypi-0.1.1` | PyPI, 2026-08-10 | no | `pypi-0.1.0`, `git-46d41e6`, `pr4`, `pr5` |
| `pypi-0.1.2` | PyPI, 2026-08-25 | no | `pr6` |
| `git-46d41e6` | `main` before the fix | no | `pypi-0.1.0`, `pypi-0.1.1`, `pr4`, `pr5` |
| `git-main-cc3859a` | `main` after PR #9 | yes | none |
| `pr2` | open PR #2, memory-safe scoring | no | none |
| `pr4` | open PR #4, conformance tests only | no | `pypi-0.1.0`, `pypi-0.1.1`, `git-46d41e6`, `pr5` |
| `pr5` | open PR #5, control examples only | no | `pypi-0.1.0`, `pypi-0.1.1`, `git-46d41e6`, `pr4` |
| `pr6` | open PR #6, metric changes for 0.2.0 | no | `pypi-0.1.2` |
| `pr8` | open PR #8, MMD memory | no | none |
| `pr11` | open PR #11, Moran self-neighbours | yes | none |

## What the measurements show

Every variant scored the same 24 cases with seed 0: the 150-cell samples that ship with veckit (Task 1 copy-last and a partial shift; Task 2 heart copy-last, 12 proper rotations, a mirror and two rescalings; Task 3 wild type, three response strengths and the knockout itself). `pypi-0.1.2` and `main` also scored 14 cases (12 rotations, a mirror and the unrotated cells) on a 3,000-cell random subsample of the released E9.5 MERFISH file. All numbers are in [`RESULTS.md`](RESULTS.md), generated from [`results/grid.csv`](results/grid.csv) (6,701 rows, no errors).

| finding | measured |
|---|---|
| Proper rotations change `occupancy_dice` / `sliced_wasserstein` without the fix | 4 of 12 rotations on the samples (max change 0.37 / 0.038); 5 of 12 on real E9.5 (max 0.17 / 0.029) |
| Same, with the fix (`main`, `pr11`) | 0 of 12 on both |
| A mirror image (z flipped) | changes the value with the fix (0.37 on the samples), as intended; leaves it unchanged without the fix |
| Variants that differ from `main` on Task 2 shape metrics | every variant without the fix, in 5 of 17 cases (the 4 changing rotations and the mirror) |
| `pr2` changes `de_score` | 16 of 17 Task 2 cases, by up to 0.0098; no other variant changes it |
| The fix also moves ordinary, unrotated predictions | Task 3 `occupancy_dice` differs between no-fix variants and `main` in 4 of 5 cases (max 0.0105) |
| `pr8` | differs from `main` only on the shape metrics the issue #7 fix changes |
| `pr11` | identical to `main` on every metric and case |
| Task 1 | no metric differs between any two variants |

Leaderboard points: skill = min(1, |c - f| / (|c - f| + max(0, c - v))) for value v, floor f and ceiling c of `occupancy_dice` on that board, and points = 100 x (1/12) x the change in skill, 1/12 being the metric's headline weight. Computed with [`../metric-lens/`](../metric-lens/) for the real-scale drop (v = 0.828). The larger drop on the 150-cell samples (0.37) would cost 4.6 to 5.8 points on the three boards. `sliced_wasserstein` has no board anchor, so it does not affect the headline.

## Limits

- The cases are small. They show which metrics change between versions, not how large the change is on every real submission. The real-scale check covers rotation and mirroring only.
- The scorer behind the leaderboard is not published, so this cannot say which version produced your board numbers.
- Open pull requests may change before they are merged. The registry records the branch heads fetched on 2026-10-14.

## Reproduce

```bash
export SCORER_VARIANTS=/path/to/scratch     # wheels, worktrees, environments and raw records go here
pip download veckit==0.1.0 veckit==0.1.1 veckit==0.1.2 --no-deps -d "$SCORER_VARIANTS/pypi"   # then unzip each into $SCORER_VARIANTS/wheels/
git clone https://github.com/aristoteleo/veckit "$SCORER_VARIANTS/veckit-git"           # then git fetch origin pull/N/head:prN for N in 2 4 5 6 8 11
bash build_envs.sh                          # worktrees and one uv environment per variant, plus a tools env (numpy, anndata, pytest)
export VEC_E95_H5AD=/path/to/E9.5.h5ad     # optional, enables the real-scale cases
python run_grid.py prepare && python run_grid.py run && python run_grid.py run --real && python run_grid.py collect
python summarise.py                         # writes RESULTS.md
python make_registry.py --variant NAME=DIR ...   # rebuilds variants.json, one --variant per unpacked wheel or worktree
python -m pytest -q test_which_veckit.py
```

The whole grid takes about 30 minutes on an 8 GB laptop, scoring one case at a time.
