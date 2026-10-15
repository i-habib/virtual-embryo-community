---
name: vec-board-genes
description: Fetches a board's ordered gene list from the organisers' panels index, verifies its published hash, and reorders or subsets a prediction to that list without inventing genes. Use before writing or fixing any prediction for a board, and whenever a prediction's gene names or order may differ from the board panel.
---

# Match a prediction to its board's gene panel

Official data page (https://virtualembryo.ai/challenge/data), on the board panels:

> Take the panel from here rather than from a data file, no released stage is guaranteed to match a board, and a submission whose genes are right but ordered differently is rejected just the same.

Take the panel from the index, not from a training file. The same genes in another order are rejected at upload, so the order is part of the contract.

## Steps

1. Fetch the index. The panels host answers the default User-Agent with 403, so send a browser-like one:

   ```bash
   mkdir -p panels
   curl -sfL -A "Mozilla/5.0" https://virtualembryo.ai/challenge/panels/index.json -o panels/index.json
   ```

2. Read the board entry for the key you are answering, such as `T2:heart:val_interp`. The entry gives `genes_file`, `genes_sha256` and `n_genes`:

   ```bash
   python3 -c "import json; b=json.load(open('panels/index.json'))['BOARD_KEY']; print(b['genes_file'], b['genes_sha256'], b['n_genes'])"
   ```

3. Fetch the gene file into `panels/` and verify it. The published hash is the SHA-256 of the names joined by newlines, with the first 16 hex digits kept. The same rule is in `gene_hash` in `test-phase-switchover/check_test_contract.py`.

   ```python
   import hashlib, pathlib, sys
   names = [l.strip() for l in pathlib.Path(sys.argv[1]).read_text().splitlines() if l.strip()]
   print(len(names), hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()[:16])
   ```

   Save the snippet as `verify_panel.py` outside `panels/`, and run `python3 verify_panel.py panels/GENES_FILE`. Compare both printed values with `n_genes` and `genes_sha256`. Stop on any mismatch, and do not use a panel file that fails the hash.

4. Compare the prediction's gene names with the verified panel, and fail on duplicates:

   ```python
   import anndata as ad
   names = [l.strip() for l in open("panels/GENES_FILE") if l.strip()]
   a = ad.read_h5ad("PRED.h5ad")
   assert len(set(a.var_names)) == a.n_vars, "duplicate gene names"
   missing = [g for g in names if g not in set(a.var_names)]
   extra = [g for g in a.var_names if g not in set(names)]
   print(len(missing), "missing;", len(extra), "extra")
   ```

5. Subset and reorder when nothing is missing:

   ```python
   b = a[:, names].copy()   # panel order; obs and obsm rows are untouched
   ```

   The extra genes are dropped. Write their names to `dropped_genes.txt`, and count them in the ledger notes.

6. Handle missing genes explicitly. Do not add them silently. Either fix the generator so it predicts them, or add them as zero columns in panel order and write each added name to `zero_filled_genes.txt`. A zero in log1p(CP10k) values says the gene is not expressed. It is an assertion, so record it and say why.

7. Write the output under a new name, hash it, and run the board check:

   ```bash
   shasum -a 256 PRED_ORDERED.h5ad
   python test-phase-switchover/check_test_contract.py PRED_ORDERED.h5ad BOARD_KEY --index panels/index.json --panels-dir panels
   ```

## Limits

- The gene check covers names and order only. It does not check the expression scale or values, which [vec-check-submission](../vec-check-submission/SKILL.md) and the community checkers cover.
- The hash covers the gene names, not the cell rows or the coordinates.
- A subset is a different prediction. Record the step in the ledger, using [vec-submission-ledger](../vec-submission-ledger/SKILL.md), so the file's generating command shows the reorder.
