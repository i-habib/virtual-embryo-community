# 我正在运行哪个 veckit 评分器？

本文为英文 README 的中文翻译；如有出入，以英文版和官方页面为准。

Virtual Embryo 挑战赛中有多个版本的 `veckit` 评分器在流通，它们的代码并不相同。两个人对同一文件评分，可能得到不同的数字，而输出中没有任何内容说明是哪个版本产生的。本目录通过对代码做哈希来识别各个版本，测量这些差异对各项指标的影响，并提供一条命令来检查你自己安装的版本。

这是社区的分析。组织方的评分器和页面才是权威来源，排行榜实际运行的版本并未公开。

## 简要结论

- **`pip install veckit` 安装的是 0.1.2，它就是尚未合并的 PR #6 分支。** 其 14 个评分模块与 GitHub 上的 `feat/metric-hardening-0.2.0` 逐字节完全相同。该版本于 2026-08-25 发布，此后未再更新。
- **0.1.2 不包含 [issue #7](https://github.com/aristoteleo/veckit/issues/7) 的修复**，该修复于 2026-10-02 以 PR #9 合并入 GitHub 的 `main` 分支。缺少该修复时，对正确的 3D 预测进行某些真旋转（proper rotation，即不含镜像翻转的旋转）会降低 `occupancy_dice`。在已发布的 E9.5 MERFISH 文件的 3,000 个细胞上，对一个完美预测进行的 12 次随机旋转中，有 5 次使 `occupancy_dice` 从 1.0 降至低至 0.83。按已公布的锚点（anchors）计算，这一下降在心脏插值排行榜上最多损失 1.7 分，在心脏外推排行榜上最多损失 3.4 分，而在胚胎排行榜上没有影响，因为 0.83 仍高于上限（ceiling）。
- **0.1.2 会报告三个排行榜不排名的指标**：`scale_ratio` 和 `size_fidelity`（任务 2），以及 `severity_ratio`（任务 3）。其代码注释称这些比率为 "what ranks"（用于排名）。排行榜的约定（[`panels/index.json`](https://virtualembryo.ai/challenge/panels/index.json)）则以 `scale_log_ratio` 和 `severity_slope` 作为锚点，而[评估页面](https://virtualembryo.ai/challenge/evaluation?task=3&section=scoring)（任务 3 > Scoring）指明的是 `common/core_metrics.py::severity_slope`。
- **GitHub 的 `main` 分支（提交 `cc3859a`）包含该修复，并具有排行榜文档中记录的指标集。** 它就是 0.1.1 加上 issue #7 的修复，别无其他改动。
- **任务 1 的分数在所有版本中都相同。**

## 检查你的安装

```bash
python which_veckit.py                # the veckit importable from this interpreter
python which_veckit.py --root DIR     # an unpacked wheel or a checkout
```

脚本会打印匹配的版本；若无法匹配，则输出 `unknown/modified` 以及有差异的文件，并对上述问题给出简单的警告。已知版本时退出码为 0，未知或已修改的版本为 1，找不到 veckit 时为 2。若多个版本的代码完全相同，它会全部列出，而不是只选其一。该脚本仅使用 Python 标准库。

在 `pip install veckit` 环境中的输出示例：

```text
result: pypi-0.1.2
byte-identical scoring modules also in: pr6
WARNING: lacks the issue #7 fix (right-handed PCA frame in common/shape_metrics.py; merged into main as cc3859a): pypi-0.1.2, pr6
WARNING: scoring modules are byte-identical to an unmerged PR branch, which is not on main: pr6
WARNING: reports severity_ratio and/or scale_ratio, which the leaderboard does not rank. ...
```

安装与文档中指标一致的版本：

```bash
pip install "git+https://github.com/aristoteleo/veckit@cc3859ab2a2305efc4544815d3f44f660efa77d4"
```

其 `pyproject.toml` 仍写着 0.1.1，因此 `pip show veckit` 无法将它与 PyPI 上的 0.1.1 版本区分开；`which_veckit.py` 可以。与他人比较数字时，双方都应先运行 `which_veckit.py`，并写明版本名。

## 版本

`variants.json` 保存了 11 个版本中 14 个评分模块（`score_h5ad.py`、`veckit.py`、`common/*.py`、`T1/*.py`、`T2/*.py`、`T3/*.py`）各自的 SHA-256 哈希值。这 11 个版本包括：三个 PyPI 发布版、`main` 上的两个提交，以及六个修改了代码的未合并拉取请求（open pull request）。

| 版本 | 说明 | issue #7 修复 | 评分代码与以下版本相同 |
|---|---|---|---|
| `pypi-0.1.0` | PyPI，2026-08-10 | 否 | `pypi-0.1.1`、`git-46d41e6`、`pr4`、`pr5` |
| `pypi-0.1.1` | PyPI，2026-08-10 | 否 | `pypi-0.1.0`、`git-46d41e6`、`pr4`、`pr5` |
| `pypi-0.1.2` | PyPI，2026-08-25 | 否 | `pr6` |
| `git-46d41e6` | `main` 在修复之前 | 否 | `pypi-0.1.0`、`pypi-0.1.1`、`pr4`、`pr5` |
| `git-main-cc3859a` | `main` 在 PR #9 之后 | 是 | 无 |
| `pr2` | 未合并的 PR #2，内存安全的评分 | 否 | 无 |
| `pr4` | 未合并的 PR #4，仅有一致性测试（conformance tests） | 否 | `pypi-0.1.0`、`pypi-0.1.1`、`git-46d41e6`、`pr5` |
| `pr5` | 未合并的 PR #5，仅有控制样例 | 否 | `pypi-0.1.0`、`pypi-0.1.1`、`git-46d41e6`、`pr4` |
| `pr6` | 未合并的 PR #6，0.2.0 版的指标改动 | 否 | `pypi-0.1.2` |
| `pr8` | 未合并的 PR #8，MMD 内存问题 | 否 | 无 |
| `pr11` | 未合并的 PR #11，Moran 自邻居（self-neighbours） | 是 | 无 |

## 测量结果

每个版本都在随机种子 0 下对相同的 24 个案例进行了评分：veckit 自带的 150 个细胞的样本（任务 1 的 copy-last 和部分平移；任务 2 心脏的 copy-last、12 次真旋转、一次镜像和两次重新缩放；任务 3 野生型、三种响应强度以及敲除样本本身）。`pypi-0.1.2` 和 `main` 还在已发布的 E9.5 MERFISH 文件的 3,000 个细胞随机子样本上，对 14 个案例（12 次旋转、一次镜像和未旋转的细胞）进行了评分。所有数字见 [`RESULTS.md`](RESULTS.md)，由 [`results/grid.csv`](results/grid.csv) 生成（6,701 行，无错误）。

| 发现 | 测量结果 |
|---|---|
| 在没有修复的情况下，真旋转会改变 `occupancy_dice` / `sliced_wasserstein` | 样本上 12 次旋转中有 4 次（最大变化分别为 0.37 / 0.038）；真实 E9.5 数据上 12 次中有 5 次（最大为 0.17 / 0.029） |
| 同样的情况，有修复时（`main`、`pr11`） | 两者在 12 次旋转中均为 0 次 |
| 镜像（z 轴翻转） | 有修复时数值会改变（样本上为 0.37），符合设计预期；没有修复时数值不变 |
| 在任务 2 形状指标上与 `main` 不同的版本 | 所有未修复的版本，在 17 个案例中的 5 个上与之不同（即 4 次会改变结果的旋转和镜像） |
| `pr2` 会改变 `de_score` | 17 个任务 2 案例中的 16 个，最大变化 0.0098；其他版本均不改变它 |
| 修复也会改变普通的、未旋转的预测 | 任务 3 的 `occupancy_dice` 在未修复版本与 `main` 之间，于 5 个案例中的 4 个上不同（最大 0.0105） |
| `pr8` | 仅在修复 issue #7 所改变的形状指标上与 `main` 不同 |
| `pr11` | 在所有指标和案例上都与 `main` 完全相同 |
| 任务 1 | 任意两个版本之间，没有任何指标不同 |

排行榜得分：对于某个排行榜上 `occupancy_dice` 的取值 v、下限 f 和上限 c，技能值 skill = min(1, |c - f| / (|c - f| + max(0, c - v)))，得分 = 100 × (1/12) × 技能值的变化量，其中 1/12 是该指标在总分中的权重。真实尺度下的下降（v = 0.828）用 [`../metric-lens/`](../metric-lens/) 计算。150 个细胞样本上较大的下降（0.37）会在三个排行榜上损失 4.6 到 5.8 分。`sliced_wasserstein` 没有排行榜锚点，因此不影响总分。

## 局限

- 案例规模较小。它们说明了哪些指标在版本之间会发生变化，但并不能说明每一份真实提交的变化有多大。真实尺度的检查只涵盖旋转和镜像。
- 排行榜背后的评分器未公开，因此无法判断哪个版本产生了你在排行榜上的数字。
- 未合并的拉取请求在合并前可能会改动。注册表记录的是 2026-10-14 获取的分支头（branch heads）。

## 复现

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

在 8 GB 内存的笔记本上，整个网格大约需要 30 分钟，每次只对一个案例评分。
