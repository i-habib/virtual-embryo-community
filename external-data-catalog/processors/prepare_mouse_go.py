#!/usr/bin/env python3
from __future__ import annotations
import argparse
import csv
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vec_external.common import load_gene_list, open_text_maybe_gzip


def main():
    p = argparse.ArgumentParser(description="Extract mouse GO annotations for a VEC gene panel.")
    p.add_argument("gaf", type=Path, help="MOUSE-mod.gaf.gz from Gene Ontology / MGI")
    p.add_argument("--gene-list", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--exclude-iea", action="store_true", help="drop IEA electronic annotations")
    args = p.parse_args()
    wanted = set(load_gene_list(args.gene_list))
    rows = []
    with open_text_maybe_gzip(args.gaf) as f:
        for line in f:
            if not line or line.startswith("!"):
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 15:
                continue
            symbol, qualifier, go_id, reference, evidence, aspect, name, synonyms = (
                cols[2], cols[3], cols[4], cols[5], cols[6], cols[8], cols[9], cols[10]
            )
            if symbol not in wanted:
                continue
            if args.exclude_iea and evidence == "IEA":
                continue
            if "NOT" in qualifier.split("|"):
                continue
            rows.append((symbol, go_id, aspect, evidence, qualifier, reference, name, synonyms))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["gene", "go_id", "aspect", "evidence", "qualifier", "reference", "gene_name", "synonyms"])
        w.writerows(rows)
    print(f"wrote {len(rows)} gene-GO edges covering {len({r[0] for r in rows})} requested genes")

if __name__ == "__main__": main()
