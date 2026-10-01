# Scale check

The CI stress test uses synthetic sparse expression with the full Task 1 gene width:

```bash
python benchmarks/stress_sparse.py \
  --cells 10000 \
  --mean-cells 1000 \
  --genes 32285 \
  --density 0.02
```

Observed on GitHub's Ubuntu runner in CI run `36794571097` (2026-09-30):

| path | size | result |
|---|---:|---|
| population mixture | 10,000 × 32,285 | output stayed sparse, 1.86 s |
| mean graft | 1,000 × 32,285 | float32 chunked output, 0.26 s |
| whole stress process | both above | peak RSS 525.84 MiB |

This is a regression-scale check, not a hardware-independent performance claim. The synthetic inputs are 2% sparse. Population mixing keeps sparse storage. Mean graft and quantile graft currently return dense float32 expression, so their output storage still grows linearly with `cells × genes`.
