# history-rescore（历史提交的本地重新评分）

本文为英文 README 的中文翻译；如有出入，以英文版和官方页面为准。

在验证集答案公布后，在本地对团队提交过的每个文件重新评分。

E10.5 任务 1、E7.5 胚胎、E8.5 心脏插值、E10.5 心脏外推以及 Gata4 敲除（KO）的验证集答案将于 2026 年 10 月 20 日公布，即测试阶段开始的那天。在此之前，团队对每个已提交文件只能看到一个总分。拿到答案后，团队可以在自己的机器上对全部提交历史重新评分。这能带来三个好处：

1. 团队提交过的每个文件的分指标明细，而不只是总分；
2. 本地重新评分与排行榜数字的吻合程度，按排行榜逐一统计；
3. 团队自己的哪些本地验证信号与排行榜走势一致。

这些信息是选择两次最终测试提交的依据。测试阶段不提供任何反馈，因此提交历史是唯一可用的证据。

相关工具：[vec_local_score](https://github.com/xxx12e/vec-community-kit)（位于 vec-community-kit 中）在伪划分（pseudo split）上实现了评分协议，本工具不重复这一范围。[vecbench](https://github.com/AJK0921/vecbench) 对本地留出集与排行榜做秩相关分析，本工具则对团队已提交的文件做同类的秩检查。

## 环境要求

- Python 3.9 或更高版本，并安装 `numpy`、`scipy`、`anndata` 和 `pytest`。
- `veckit`，版本为本工具构建时所用的固定提交：

  ```bash
  pip install "git+https://github.com/aristoteleo/veckit@cc3859a" anndata numpy scipy pytest
  ```

- 与本文件夹位于同一仓库中、并与本文件夹相邻的 `metric-lens` 文件夹。总分公式和权重均来自该文件夹。

## 三个步骤

### 1. 导出提交表

打开 <https://virtualembryo.ai/challenge/account/submissions>，展开列表直到显示所有行，然后将 `export_submissions.js` 粘贴到浏览器控制台中。该脚本会保留已评分的行，并下载 `submissions.csv`，其列为 `submitted,task,file,board,board_score`。

`board` 列是根据任务和文件名推测的结果：

- `T1` 对应 `T1:val`；
- `T2 · embryo` 对应 `T2:embryo:val_interp`；
- `T2 · heart` 若文件名提及 E8.5 或 interp，则对应 `T2:heart:val_interp`；若提及 E10.5 或 extrap，则对应 `T2:heart:val_extrap`；
- `T3` 对应 `T3:gata4`。

推测结果为空的行（包括文件名同时提及两者或两者都不提及的每个心脏文件）必须在下一步之前手动填写。测试阶段排行榜应使用面板索引（panel index）中的键，因为脚本不会对这些排行榜进行推测。

### 2. 文件发布后编写 boards.json

`boards.json` 将每个排行榜键映射到已发布的文件。路径相对于 `boards.json` 文件本身。

```json
{
  "T1:val": {"target": "released/T1_E10.5.h5ad", "reference": "released/E9.5_RNA.h5ad"},
  "T2:heart:val_extrap": {"target": "released/heart_E10.5.h5ad", "reference": "released/heart_E9.5.h5ad", "setting": "heart"},
  "T3:gata4": {"target": "released/gata4_ko.h5ad", "wt": "released/wt.h5ad"}
}
```

- `reference` 是排行榜 copy-last 下限所来自的阶段，改动以此为基准进行衡量（对于 `T1:val`，即 E9.5；索引中其 `ref_cells` 为 1,706，即 E9.5 的 17,057 个细胞的 10%）。对于任务 3，使用 `wt`。
- 对于任务 2，`setting` 为 `heart` 或 `embryo`。
- `target_is_working_copy` 和 `reference_is_working_copy`（默认为 `false`）：若已发布的文件本身已经是 10% 的工作副本，则设为 `true`，以免被二次下采样。
- `weights_from` 仅在某个测试阶段排行榜无法按名称与某个验证集排行榜对应时才需要。
- `fraction`（默认为 0.1）是排行榜协议中的下采样比例。对真实排行榜请保持默认值。

### 3. 运行

```bash
python rescore.py \
  --submissions submissions.csv \
  --search ~/Downloads/vec-files ~/Projects/vec-runs \
  --boards boards.json \
  --protocol board --seeds 3 \
  --out results/
```

分别用 `--protocol board` 和 `--protocol full` 各运行一次，并比较两份报告。

选项：

- `--search` 接受一个或多个文件夹。每个提交的文件按文件名递归查找。
- 两个不同的文件同名时，`--prefer DIR` 用于决定使用哪一个。未指定时使用最新的文件，并写入警告。
- `--index FILE` 使用面板索引的已保存副本。未指定时，下载实时索引。工具从索引中读取锚点和细胞数上限，因此测试阶段的排行榜无需修改代码。
- `--local-validator FILE` 接受一个包含 `file,board,value` 列的 CSV 文件，例如团队自己的某个验证指标，并增加该指标与排行榜以及与本地总分的秩一致性。
- `--guess-blank` 使用导出规则填充空白的排行榜单元格，并对每个推测给出警告。请手动检查这些推测。
- `--keep-work` 将派生的 10% 工作副本保留在 `results/work/` 中。默认会删除这些副本。

## 协议

- `board` 遵循[数据页面](https://virtualembryo.ai/challenge/data)中描述的协议（“How many cells to submit”，即应提交多少细胞）：评分器将每个阶段下采样到 10%，将目标一分为二，用其中一半评分，并用另一半计算上限。这里，每个阶段都以一个随机种子下采样到 10%。目标被一分为二，预测与其中的 A 半进行评分。参考数据使用其自身的 10% 工作副本。每个种子都会给出不同的子样本和不同的划分。
- `full` 将预测与整个已发布的目标进行评分。此时种子只改变评分器内部的随机性。

## 输出

- `results/rescore.csv`：每个提交行一行。包含排行榜分数、状态（`scored`、`missing_file`、`no_board`、`board_not_configured`、`scoring_error` 或 `scored_ambiguous_name`）、本地总分在各种子上的均值和标准差、与排行榜的差值，以及每个指标的原始值均值和技能值均值。
- `results/RESCORE.md`：先是覆盖情况（缺失、空白和失败的行），然后针对每个排行榜列出：文件数、本地值减排行榜值的均值和标准差、本地与排行榜总分之间的 Spearman 秩相关系数、五个最大的分歧，以及每个指标的技能值与排行榜分数之间的秩相关系数。`n/a` 表示该值无定义，原因是文件少于三个，或该指标在各文件间没有变化。
- `results/scores.jsonl`：每个文件、排行榜、协议和种子占一行，包含原始指标。重新运行时会读取此文件，只对缺失的部分评分。更改某排行榜的已发布文件或评分器会改变键值，因此受影响的文件会被重新评分。
- `results/index_used.json`：本次运行所用的面板索引副本。

如何解读数字：本地值减排行榜值的差较小，说明本地协议对该文件复现了排行榜结果。秩相关说明文件的排序是否一致，而分指标表说明是哪个指标带动了排行榜的变化。文件较少时，这些相关系数并不稳定，因此应结合 n 一起看。

## 局限

- 排行榜使用的确切子样本未公开。在 board 协议下，本地总分会随种子变化，因此会存在噪声。下方的演示在 150 个细胞的合成数据上测得，board 协议下种子标准差为 1.09 分。真实阶段的细胞更多，噪声可能更小，但应在数据发布后实际测量，而不要假定。
- 已发布的真值可能是完整阶段，也可能是 10% 工作副本。应在发布时确认是哪一种，并相应设置 `*_is_working_copy` 标志。
- 本地重新评分是对已提交文件的分析，它不是分数，也无法给出隐藏的测试结果。在旧文件上与排行榜一致，并不能保证最终测试提交的排名。
- 文件按名称匹配。在搜索文件夹中，两个不同的同名文件构成冲突，工具会明确指出。
- 权重和方向（directions）来自 `metric-lens` 中排行榜定义的副本，锚点来自实时索引。若两者不一致，工具会发出警告并使用索引中的值。
- 在 full 协议下，每个文件都会加载整个目标数据，且每次在单独的进程中只处理一个文件。开发所用的机器有 8 GB 内存。演示在 150 个细胞时，每个评分进程的峰值约为 300 MB。这并不能说明完整发布数据所需的内存，因此应在第一次全尺寸运行时检查内存占用。
- `export_submissions.js` 依赖提交表的版式。若缺少某一列，它会停止运行，并列出它找到的表头。

## 演示

`demo/run_demo.sh` 在合成数据上运行全部流程。它会从 GitHub 按固定提交下载 veckit 公开的 150 个细胞的心脏样本。参考为 `sample_heart_9.25`，目标为 `sample_heart_9.5`。六个预测仅通过对参考进行变换得到：直接复制、向均值收缩、分别乘以 1.2 和 0.8 进行缩放、将坐标旋转 30 度，以及与打乱顺序的副本混合。每个文件的排行榜分数为使用索引中的锚点和权重进行的一次完整评分，再加上标准差为 1.0 的高斯噪声。这些并非真实的排行榜数值。该演示用于检验流程，并展示本地重新评分与带噪声的排行榜相比的表现。

```bash
PY=python3 ./demo/run_demo.sh
```

本 README 所用运行的结果：

- full 协议，对 5 个文件评分：本地值减排行榜值的均值为 0.04，标准差为 0.23。本地总分的种子标准差平均为 0.13。Spearman 秩相关 0.975（n=5）。
- board 协议、下采样比例为 0.5，对 5 个文件评分：本地值减排行榜值的均值为 0.34，标准差为 0.50。本地总分的种子标准差平均为 1.09。Spearman 0.975（n=5）。

关于这些数字的说明：

- 下采样比例为 0.5 而非 0.1。在 0.1 时，150 个细胞的样本在对半划分后只剩 7 个细胞，而 veckit 在 15 个细胞的目标上会失败。在 0.5 时，目标的 A 半有 37 个细胞。
- 合成噪声偶然抽到了较小的值。full 运行中的差值标准差为 0.23，小于注入噪声的标准差 1.0，因此它们并不能衡量真实排行榜的噪声。
- 空间指标 `d2_shape`、`occupancy_dice` 和 `scale_log_ratio` 在这些预测之间没有变化，因此它们的秩相关为 `n/a`。
- 第 6 行的排行榜为空，第 7 行所指的文件不在磁盘上。报告在覆盖情况中同时列出了这两项。

演示会将生成的文件写入 `demo/`。文件夹 `demo/data/` 和生成的结果不纳入版本控制。
