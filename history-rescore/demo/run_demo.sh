#!/usr/bin/env bash
# Reproduce the synthetic demo end to end.
# Needs a Python with veckit (git commit cc3859a), anndata, numpy and scipy:
#   PY=/path/to/python ./run_demo.sh
# Downloads veckit's public 150-cell heart samples from GitHub at a pinned commit.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python3}"
VECKIT_COMMIT="cc3859ab2a2305efc4544815d3f44f660efa77d4"
RAW="https://raw.githubusercontent.com/aristoteleo/veckit/${VECKIT_COMMIT}/data"

mkdir -p "$HERE/data"
for f in sample_heart_9.25.h5ad sample_heart_9.5.h5ad; do
  if [ ! -s "$HERE/data/$f" ]; then
    curl -fsSL -o "$HERE/data/$f" "$RAW/$f"
  fi
done

rm -rf "$HERE/team_files" "$HERE/results_full" "$HERE/results_board"
"$PY" "$HERE/make_demo.py" --data "$HERE/data" --out "$HERE" > "$HERE/make_demo_audit.json"

for protocol in full board; do
  "$PY" "$HERE/../rescore.py" \
    --submissions "$HERE/submissions.csv" \
    --search "$HERE/team_files" \
    --boards "$HERE/boards.json" \
    --index "$HERE/index_snapshot.json" \
    --protocol "$protocol" --seeds 3 \
    --out "$HERE/results_$protocol"
done

echo "Done. See $HERE/results_full/RESCORE.md and $HERE/results_board/RESCORE.md"
