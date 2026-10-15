---
name: vec-submission-ledger
description: Keeps an append-only CSV ledger of every prediction file an agent writes and every upload, with SHA-256, board, time, generating command and local score, so the final submissions can be chosen and the uploaded bytes can be proven. Use whenever a prediction is written, scored or uploaded, and when choosing the two final files per board.
---

# Keep a submission ledger

Official rule, rules section 12 (https://virtualembryo.ai/challenge/rules):

> Keep your own copy of everything you submit. A prediction that exists only on our disk is one you cannot send again.

Rules section 11 allows "2 official submissions per board, for the whole phase rather than per day", and each one "cannot be withdrawn". Each upload uses up one of those slots, so the ledger is the record that shows which bytes went up.

## The ledger

Keep one file, `ledger/submissions.csv`, outside the agent's workspace. Use these columns:

`event,utc_time,run_id,board_key,file_path,sha256,bytes,generating_command,local_scorer,local_score,upload_receipt,notes`

- `event` is `predict` when a file is written, `score` when it is scored, `upload` when it is sent, and `choose` when a person picks a final file.
- `sha256` and `bytes` come from the file itself, read at the time of the row.
- `generating_command` is the exact command that wrote the file, including the script's commit hash.
- `local_scorer` is the veckit variant reported by `python scorer-versions/which_veckit.py`. `local_score` is the Metric Lens total for that board, as described in [vec-score-locally](../vec-score-locally/SKILL.md).
- `upload_receipt` is the confirmation ID the portal gives for that upload.

Only append rows. Never edit or delete one. A correction is a new row whose `notes` explain it.

## Steps

1. Write each prediction to a new name, and make the writer refuse an existing path. In the shell, run `set -C` so that `>` cannot overwrite a file. In Python, open the output with mode `"x"`.

2. Append a `predict` row as soon as the file exists. Use a short script, so the hash comes from the file and not from memory:

   ```python
   import csv, hashlib, pathlib, sys, datetime
   path = pathlib.Path(sys.argv[1])
   data = path.read_bytes()
   row = {"event": sys.argv[2], "utc_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "run_id": sys.argv[3], "board_key": sys.argv[4], "file_path": str(path),
          "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
          "generating_command": sys.argv[5], "local_scorer": sys.argv[6], "local_score": sys.argv[7],
          "upload_receipt": sys.argv[8] if len(sys.argv) > 8 else "",
          "notes": sys.argv[9] if len(sys.argv) > 9 else ""}
   out = pathlib.Path("ledger/submissions.csv")
   out.parent.mkdir(parents=True, exist_ok=True)
   is_new = not out.exists()
   with out.open("a", newline="") as fh:
       writer = csv.DictWriter(fh, fieldnames=list(row))
       if is_new:
           writer.writeheader()
       writer.writerow(row)
   ```

   The script takes the file, then six values in this order: `event` (`predict`, `score` or `upload`), `run_id`, `board_key`, `generating_command`, `local_scorer` and `local_score`. Two optional arguments follow: the `upload_receipt` and the `notes`. Pass an empty string for any value that does not apply.

3. Make the file read-only with `chmod a-w FILE`, and keep it in the same folder as its ledger rows.

4. Check the file before you upload it, with the board's contract checker:

   ```bash
   python test-phase-switchover/check_test_contract.py PRED.h5ad BOARD_KEY
   ```

   Format checks are free. Rules section 11: "Format checks are unlimited in every phase and spend nothing." Upload only a file that passes.

5. Upload, then hash the same file again before you append the `upload` row. If the hash differs from the `predict` row, stop and report it. Record the portal's receipt in `upload_receipt`.

6. Choose the final files from the `upload` rows, not from memory. Rules section 9 says that "Choosing which completed run to submit is a person's decision." Record that choice as a `choose` row with the person's name in `notes`.

## Limits

- The ledger proves which bytes were uploaded only if the hash at upload matches the `predict` row. It says nothing about the run that made the file. For that, use [vec-record-provenance](../vec-record-provenance/SKILL.md).
- The local score is a guide to choosing among candidates. It is not the board score, and rules section 10 says returned scores are for choosing, not for computing predictions.
