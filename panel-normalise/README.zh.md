# Virtual Embryo 数据的基因面板归一化

本文为英文 README 的中文翻译；如有出入，以英文版和官方页面为准。

`vec_normalise.py` 将原始计数矩阵中的小鼠基因名映射到挑战赛的基因面板（gene panel）上，并且只用面板基因计算自然对数形式的 CP10k（即先做 CP10k 再取 log1p），使数值与挑战赛发布的数据一致。

本文用到的术语：

- **CP10k**：每个细胞的计数除以该细胞在面板基因上的总和，再乘以 10,000。
- **自然 log1p**：在 CP10k 之后取 log(1 + x) 的自然对数。
- **面板（panel）**：排行榜为每个任务提供的有序基因列表，可从 <https://virtualembryo.ai/challenge/data> 下载。任务 2 和任务 3 的 MERFISH 面板约有 500 个基因。任务 1 的列表（`T1__val.genes.txt`）有 32,285 个基因。
- **MGI**：小鼠基因组信息学（MGI, Mouse Genome Informatics）的基因命名表。`MRK_List2.rpt` 给出当前符号和同义词，`MRK_ENSEMBL.rpt` 给出小鼠 Ensembl 基因 ID。除非用 `--mgi-dir` 指定本地副本，否则工具会下载这两个文件。

## 为什么顺序很重要

在 GSE193346 的 E9.5 心脏单细胞 RNA 测序（scRNA-seq）数据（887 个细胞）中，按符号精确匹配的 498 个面板基因，占每个细胞计数的中位数为 5.3%（第 5 到第 95 百分位：0.8% 到 7.8%）。如果先在全部基因上归一化、再选取面板基因，那么面板基因的数值在每个细胞中的求和中位数为 529，而不是 10,000。此时它们的 log1p 值在非零项上平均偏低 2.3，最大偏差达到 5.3。

## 安装与测试

```sh
python -m pip install anndata numpy pandas scipy pytest
python -m pytest -q
```

测试在 Python 3.11、anndata 0.12.19、pandas 2.3.3、numpy 2.4.6 和 scipy 1.17.1 环境下通过。本 README 中的真实数据运行使用 Python 3.13、anndata 0.13.4、pandas 3.0.6、numpy 2.5.3 和 scipy 1.18.1。

## 命令

```sh
# Report how each input column resolves, without writing a matrix
python vec_normalise.py resolve raw.h5ad --panel T2__heart__val_interp.genes.txt --mgi-dir mgi --report mapping.tsv

# Normalise raw counts over a panel (Tasks 2 and 3)
python vec_normalise.py normalise raw.h5ad --panel T2__heart__val_interp.genes.txt --out panel.h5ad --mgi-dir mgi --report mapping.tsv

# Normalise over the Task 1 list, zero-filling genes the input lacks
python vec_normalise.py normalise raw.h5ad --panel T1__val.genes.txt --out task1.h5ad --fill-missing zeros

# Check a release file against its counts layer
python vec_normalise.py verify release.h5ad --panel T2__heart__val_interp.genes.txt
```

输入必须是原始计数，可以在 `X` 中，也可以在用 `--layer` 指定的层中。要求为整数值。`--allow-noninteger` 允许以浮点数存储的原始计数，但会拒绝看起来经过对数变换的矩阵（即所有值都小于 20 且 expm1 行和为常数）。若要检查一个文件保存的是计数还是对数值，请使用 [vec-logcheck](https://github.com/random-guy-05/vec-logcheck)。本工具只保留上文所述的最低限度检查。

## 基因名如何匹配

输入的每一列至多对应一个面板符号，判定顺序如下：

- **exact（精确匹配）**：名称与某个面板符号相同。
- **rescued（挽救匹配）**：仅大小写不同的当前符号、小鼠 Ensembl 基因 ID（忽略版本后缀）或 MGI 同义词，映射到一个没有被任何精确匹配列占用的面板基因。
- **conflict（冲突）**：挽救匹配的目标面板基因已被某个精确匹配列占用。此时拒绝该挽救匹配。例如，当 `Pakap` 也是输入列时，`Pakap` 的同义词 `Palm2` 会被拒绝。
- **ambiguous（歧义）**：仅大小写不同的键或同义词对应多个当前基因符号，其中有一个在面板中。拒绝该挽救匹配。名称 `t` 不会被映射到面板基因 `T`。
- **unmatched（未匹配）**：没有面板基因与之匹配。
- **missing（缺失）**：面板基因在输入中没有对应列。除非给出 `--fill-missing zeros`，否则归一化会停止。

只有 MGI 中类型为 `Gene` 和 `Pseudogene` 的记录可以作为目标。其他标记类型的当前符号永远不会成为某个基因的同义词。Ensembl ID 通过 MGI 登录号（accession）与符号关联。MGI 已不再列出的 Ensembl ID 视为未匹配。

映射到同一面板基因的输入列会先以原始计数相加，然后才应用 CP10k。分母是输入中面板基因的求和，因此补零的基因不会改变总量。

## 输出

输出包含按面板顺序排列的 `var_names`、float32 格式的 CSR 矩阵 `X`，以及输入的 `obs`。`var['filled_zero']` 标记补零的基因。`uns['vec_normalise']` 记录输入和面板的校验和、MGI 报告的 URL、校验和与下载日期（下载报告时写入一次）、映射计数、补零的基因，以及接收了求和列的目标基因。`uns['vec_normalise_mapping']` 保存完整的映射表。`--report` 文件与该表相同，为 TSV 格式。

## 实测结果

计数来自对每个输入运行 `resolve` 的结果，行和检查来自对相同输入运行 `normalise` 的结果。面板即排行榜的基因列表。GSE193346 E9.5 的输入为整数原始计数。GSE150817 E16.5 的输入是 4,200 个细胞的稀疏原始计数矩阵，由 [scripts/rebuild_gse150817_counts.py](scripts/rebuild_gse150817_counts.py) 从公开的 UMI 表重建。

| 输入与面板 | 精确匹配 | 挽救匹配 | 冲突 | 歧义 | 未匹配的输入列 | 缺失的面板基因 | 输出（细胞 × 基因） |
|---|---:|---:|---:|---:|---:|---:|---:|
| GSE193346 E9.5，任务 2 心脏 | 498 | 2 | 0 | 0 | 30,476 | 0 | 887 × 500 |
| GSE193346 E9.5，任务 1 列表 | 29,715 | 227 | 7 | 3 | 1,024 | 2,343 | 887 × 32,285 |
| GSE150817 E16.5，任务 2 心脏 | 468 | 0 | 0 | 0 | 22,781 | 32 | 4,200 × 500 |
| GSE150817 E16.5，任务 1 列表 | 19,320 | 1 | 2 | 0 | 3,926 | 12,964 | 4,200 × 32,285 |

每个输出的 expm1(X) 行和都在 9,999.99 到 10,000.01 之间，因此每个细胞在面板基因上的 CP10k 总和为 10,000。

表中的挽救匹配示例：`Wisp2` 映射到 `Ccn5`，`Tmem2` 映射到 `Cemip2`，`3110035E14Rik` 映射到 `Vxn`（任务 1 列表）。被拒绝的示例：`Palm2` 是 `Pakap` 的同义词，但由于 `Pakap` 是精确匹配的输入列，它被报告为冲突。

已发布的任务 1 和 MERFISH 文件的归一化方式见 [NORMALISATION.md](NORMALISATION.md)。

## 与外部数据目录的关系

本仓库中的[外部数据目录（External Data Catalog）](../external-data-catalog/)包含 Tabula Muris 和 Extended Mouse Atlas 的处理程序。这些处理程序在归一化之前先截取到面板基因。本工具在此基础上增加了上文所述的别名挽救步骤和冲突检查，并采用同样的先截取面板、后归一化的顺序。
