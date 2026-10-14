# Virtual Embryo 数据安全工具包

本文为英文 README 的中文翻译；如有出入，以英文版和官方页面为准。

这是一个小型、偏保守的外部数据资格辅助工具。它要回答的问题很窄：**这一数据来源是否违反了某条可以机械检查的挑战赛规则？**

它做两件事：

- [`check_external_data.py`](check_external_data.py) 检查明确列出的阶段窗口，以及任务 3 中明确命名的条件。
- [`render_disclosure.py`](render_disclosure.py) 将数据来源登记表转换为方法报告中的披露部分。

它**不是**资格判定器（eligibility oracle）。体节（somite）/ Theiler 分期、“可比阶段”（comparable stage）、留出基因的其他等位基因，以及拟表型（phenocopying）扰动，都需要生物学判断。这些情况会返回 `ASK_ORGANIZERS`。

规则第 10 节，修订版自 2026-08-26 起生效，于 2026-10-08 核对。提交前请重新阅读[官方规则](https://virtualembryo.ai/challenge/rules)。

## 示例

```bash
# Inside the protected Task 2 heart interpolation window
python check_external_data.py --task t2-heart --stage 8.4

# A broad atlas crossing both legal and protected stages
python check_external_data.py --task t2-heart --range 8.0 9.0

# A heart stage after E9.5, the last heart stage released; referred to the organizers
python check_external_data.py --task t2-heart --stage 10.0

# Exact held-out Task 3 condition
python check_external_data.py --task t3 --gene gata4 --stage 8.75 --allele same

# An ambiguous allele/stage case
python check_external_data.py --task t3 --gene gata4 --stage 9.0 --allele other
```

可能的输出结果刻意保持简单：

- `EXCLUDED`：所提供的情况位于明确的受保护窗口或精确的留出条件之内。
- `FILTER_REQUIRED`：该资源同时包含允许使用和受保护的材料，需要过滤。
- `CLEAR_BY_STAGE_RULE` / `CLEAR_BY_NAMED_GENOTYPE_RULE`：该项机械检查未将其排除。这并不是全面批准。每个 CLEAR 结果都会重申一句话：“Every external source must be disclosed with the submission.”（所有外部数据来源都必须随提交一并披露。）
- `ASK_ORGANIZERS`：仅凭所提供的元数据，无法负责任地得出结论，需要询问组织方。

## 已编码的阶段规则

依据规则第 10 节：

- **任务 1：** `(E9.5, E13.5]` 为受保护区间。第 10 节写明：“External data is excluded from after E9.5 up to and including E13.5.”（外部数据排除 E9.5 之后直至 E13.5（含）的数据。）E13.5 之后的数据仅在明确注明来源和阶段的情况下可以使用。
- **任务 2 心脏插值：** `(E8.25, E8.75)` 为受保护区间。
- **任务 2 心脏留出阶段：** 第 10 节将 E8.5、E10.5 和 E12.5 列为留出阶段，因此 E10.5 和 E12.5 返回 `EXCLUDED`。
- **任务 2 心脏 E9.5 之后：** 第 10 节给出了 E9.5 至 E13.5 的窗口，但未指明任务；而通用规则对外推目标规定了 “everything from the midpoint onwards is treated as held out”（中点之后的一切均视为留出）。脚本没有把该窗口应用于心脏，因此心脏 E9.5 之后的阶段返回 `ASK_ORGANIZERS`。E9.5 本身是允许的。
- **任务 2 胚胎插值：** `(E7.25, E8.0)` 为受保护区间。
- **任务 3：** E8.75 的 Gata4 和 β-catenin 敲除为留出数据。相关等位基因/可比阶段以及拟表型不由脚本推测。

区间记号很重要。本工具的早期版本在“受保护开区间周围的合法端点”这一情况上出错；当前实现使用明确的开/闭区间求交，并针对这些边界设有回归测试。

## 边做边保留披露信息

从 [`sources.example.json`](sources.example.json) 开始，记录准确的数据来源、版本、许可证、阶段/条件、任务、在方法中的作用以及过滤方式。然后运行：

```bash
python render_disclosure.py sources.json --out external_sources.md
```

生成的 Markdown 本身并不重要，重要的是在截止日期前把数据来源记录下来。

## 测试

```bash
python -m unittest discover -s tests -v
```

这是独立的社区工具。组织方的指导意见和现行官方规则始终优先于本检查工具。
