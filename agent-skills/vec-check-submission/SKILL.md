---
name: vec-check-submission
description: Validates a prediction .h5ad against a board's contract in the organisers' index.json, covering gene order, cell bounds, finite non-negative X and spatial_3D where required, before any upload. Use whenever a prediction file has been written or regenerated and before it is uploaded to any board.
---

# Check a submission against its board contract

Run this before every upload. Format checks are unlimited in every phase and cost nothing (rules section 11, https://virtualembryo.ai/challenge/rules). The contract comes from https://virtualembryo.ai/challenge/panels/index.json, and the data page at https://virtualembryo.ai/challenge/data describes the boards.

## Never hand-edit a prediction

Write each prediction with the script that produces it. If the check fails, fix the generator and run it again. Do not patch the output file. Rules section 9 says a file that a person then edited is not an Agent Team entry, and a patched file breaks the provenance record in [vec-record-provenance](../vec-record-provenance/SKILL.md).

## Steps

1. List the board keys the contract currently has:

   ```bash
   python test-phase-switchover/check_test_contract.py --list
   ```

   Test boards appear in the index on 20 October 2026. Use the key from the index, not one you remember.

2. Check the file against one board:

   ```bash
   python test-phase-switchover/check_test_contract.py PRED.h5ad T2:heart:val_interp
   ```

   Options: `--index PATH` uses a saved copy of index.json, and `--panels-dir DIR` uses local gene lists. Exit code 0 means every check passed, 1 means at least one failed, and 2 means a usage or read error.

3. Read the failures, fix the generator and repeat step 2.

## What the checker covers

- The gene list matches `genes_sha256` in the index.
- `var_names` equals the board's panel, in the same order.
- The cell count is between `min_cells` and `max_cells` for the board.
- Every key in `obsm_required` is present, with one row per cell and finite values. T2 and T3 require `spatial_3D`. T1 requires nothing.
- `X` is finite and non-negative.

## What it does not cover

- The log1p(CP10k) scale and the file's SHA-256. The community checker `vec_submit_check` in https://github.com/xxx12e/vec-community-kit covers the scale.
- The organisers' upload check, which has the final say.

## Fallback when the script is missing

Use this minimal check, with the board's `genes_file`, `min_cells`, `max_cells` and `obsm_required` taken from index.json:

```python
import numpy as np
from scipy import sparse
import anndata as ad

a = ad.read_h5ad("PRED.h5ad")
panel = [line.strip() for line in open("GENES_FILE") if line.strip()]
assert list(a.var_names) == panel, "var_names differ from panel order"
assert MIN_CELLS <= a.n_obs <= MAX_CELLS, "cell count out of bounds"
vals = a.X.data if sparse.issparse(a.X) else np.asarray(a.X)
assert np.isfinite(vals).all() and (vals >= 0).all(), "X not finite and non-negative"
if "spatial_3D" in a.obsm_keys():  # required for T2 and T3 boards
    xyz = np.asarray(a.obsm["spatial_3D"])
    assert xyz.shape == (a.n_obs, 3) and np.isfinite(xyz).all(), "bad spatial_3D"
```

Fetch the gene list with a browser-like User-Agent, because the panels host answers 403 to the default one (`curl -A "Mozilla/5.0" -O URL`). The minimal check skips the `obsm_required` test for T1. Add an explicit test if a board requires another key.

## Limits

A passing check does not predict a score. Do not use the checker to test whether a change helps. Use [vec-score-locally](../vec-score-locally/SKILL.md) for that, and only against targets you are allowed to use.
