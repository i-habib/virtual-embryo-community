#!/usr/bin/env python3
"""Conservative helper for Virtual Embryo external-data eligibility.

This script only automates cases that the published rules make mechanically clear.
Anything involving somite/Theiler conversion, "comparable stage", another allele of a
held-out gene, or a phenocopy should be escalated to the organizers.

Rules snapshot: 2026-09-16
Official source: https://virtualembryo.ai/challenge/rules
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from typing import Optional

RULES_URL = "https://virtualembryo.ai/challenge/rules"
RULES_SNAPSHOT = "2026-09-16"

TASK_ALIASES = {
    "t1": "t1", "task1": "t1",
    "t2-heart": "t2-heart", "t2_heart": "t2-heart", "heart": "t2-heart",
    "t2-embryo": "t2-embryo", "t2_embryo": "t2-embryo", "embryo": "t2-embryo",
    "t3": "t3", "task3": "t3",
}

HELDOUT_GENES = {
    "gata4": "Gata4",
    "ctnnb1": "β-catenin",
    "beta-catenin": "β-catenin",
    "beta catenin": "β-catenin",
    "β-catenin": "β-catenin",
    "β catenin": "β-catenin",
}

@dataclass
class Verdict:
    status: str
    reason: str
    action: str
    task: str
    rules_snapshot: str = RULES_SNAPSHOT
    rules_url: str = RULES_URL

def canonical_task(task: str) -> str:
    key = task.strip().lower()
    if key not in TASK_ALIASES:
        raise ValueError(f"Unknown task {task!r}. Use t1, t2-heart, t2-embryo, or t3.")
    return TASK_ALIASES[key]

def protected_stage(task: str, stage: float) -> bool:
    """True only for mechanically explicit stage exclusions."""
    if task == "t1":
        return stage > 9.5 and stage <= 13.5
    if task == "t2-heart":
        return (8.25 < stage < 8.75) or (stage > 9.5 and stage <= 13.5)
    if task == "t2-embryo":
        return 7.25 < stage < 8.0
    return False

def check_stage(task: str, stage: float) -> Verdict:
    task = canonical_task(task)
    if not math.isfinite(stage):
        raise ValueError("Stage must be finite.")
    if task == "t3":
        return Verdict(
            "ASK_ORGANIZERS",
            "Task 3 eligibility depends on genotype as well as stage; a stage alone is not enough.",
            "Provide the perturbation gene/condition, and ask the organizers if stage comparability is ambiguous.",
            task,
        )
    if protected_stage(task, stage):
        return Verdict(
            "EXCLUDED",
            f"E{stage:g} falls inside a protected external-data window published for {task}.",
            "Do not use measured data from this stage for this task.",
            task,
        )
    return Verdict(
        "CLEAR_BY_STAGE_RULE",
        f"E{stage:g} is not inside a mechanically explicit protected stage window for {task}.",
        "Still check licence, provenance, hidden genotype/condition content, and the current official rules before use.",
        task,
    )

def interval_relation(task: str, lo: float, hi: float) -> Verdict:
    task = canonical_task(task)
    if lo > hi:
        lo, hi = hi, lo
    if task == "t3":
        return Verdict(
            "ASK_ORGANIZERS",
            "Task 3 restrictions are genotype-specific; a stage range alone is insufficient.",
            "Inspect the resource by genotype/condition and ask about any held-out or phenocopying perturbations.",
            task,
        )
    probes = [lo, hi]
    boundaries = {
        "t1": [9.5, 13.5],
        "t2-heart": [8.25, 8.75, 9.5, 13.5],
        "t2-embryo": [7.25, 8.0],
    }[task]
    for b in boundaries:
        if lo < b < hi:
            eps = 1e-6
            probes.extend([max(lo, b-eps), min(hi, b+eps)])
    states = [protected_stage(task, x) for x in probes]
    any_bad = any(states)
    any_good = any(not s for s in states)
    if any_bad and any_good:
        return Verdict(
            "FILTER_REQUIRED",
            f"The resource range E{lo:g}–E{hi:g} crosses both permitted and protected stages for {task}.",
            "Remove cells/samples inside the protected window before training and disclose the filtering in the method summary.",
            task,
        )
    if any_bad:
        return Verdict(
            "EXCLUDED",
            f"The supplied range E{lo:g}–E{hi:g} lies inside a protected external-data window for {task}.",
            "Do not use the measured data for this task.",
            task,
        )
    return Verdict(
        "CLEAR_BY_STAGE_RULE",
        f"The supplied range E{lo:g}–E{hi:g} does not cross a mechanically explicit protected stage window for {task}.",
        "Still inspect all conditions/genotypes, licences, and the latest official rules.",
        task,
    )

def check_t3_gene(gene: str, stage: Optional[float], allele: str, phenocopy: bool) -> Verdict:
    task = "t3"
    held = HELDOUT_GENES.get(gene.strip().lower())
    if phenocopy:
        return Verdict(
            "ASK_ORGANIZERS",
            "The rules treat perturbations that phenocopy a held-out condition as held out, and that requires biological judgment.",
            "Do not guess. Ask the organizers before using this source.",
            task,
        )
    if held:
        if stage is not None and abs(stage - 8.75) < 1e-9 and allele == "same":
            return Verdict(
                "EXCLUDED",
                f"{held} knockout data at E8.75 is a held-out Task 3 condition.",
                "Do not use it by any route, including through pretrained models or public datasets.",
                task,
            )
        return Verdict(
            "ASK_ORGANIZERS",
            f"The source involves held-out gene {held}. The rules also exclude another allele of the same gene at a comparable stage.",
            "Ask the organizers whether this stage/allele is considered comparable before use.",
            task,
        )
    return Verdict(
        "CLEAR_BY_NAMED_GENOTYPE_RULE",
        f"{gene} is not one of the two named held-out Task 3 genes.",
        "Still inspect whether the perturbation phenocopies a held-out condition and check the current rules.",
        task,
    )

def main() -> None:
    p = argparse.ArgumentParser(description="Conservative Virtual Embryo external-data rules helper. It does not replace organizer approval.")
    p.add_argument("--task", required=True, help="t1, t2-heart, t2-embryo, or t3")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--stage", type=float, help="single embryonic day, e.g. 8.4")
    g.add_argument("--range", nargs=2, type=float, metavar=("START", "END"), help="resource stage range")
    p.add_argument("--stage-label", help="non-E-day label such as somite/Theiler staging; returns ASK_ORGANIZERS")
    p.add_argument("--gene", help="perturbed gene for Task 3")
    p.add_argument("--allele", choices=["same", "other", "unknown"], default="unknown")
    p.add_argument("--phenocopy", action="store_true", help="source may phenocopy a held-out Task 3 perturbation")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()
    task = canonical_task(args.task)

    if args.stage_label:
        verdict = Verdict(
            "ASK_ORGANIZERS",
            "Somite/Theiler or other alternative staging must be mapped onto the embryonic-day scale; this helper does not automate that biological conversion.",
            "Map the stage carefully and ask the organizers if it sits near a boundary.",
            task,
        )
    elif task == "t3":
        if not args.gene:
            verdict = Verdict(
                "ASK_ORGANIZERS",
                "Task 3 eligibility is genotype-specific and no perturbation gene was provided.",
                "Provide --gene and, if relevant, --stage/--allele/--phenocopy.",
                task,
            )
        else:
            verdict = check_t3_gene(args.gene, args.stage, args.allele, args.phenocopy)
    elif args.range:
        verdict = interval_relation(task, args.range[0], args.range[1])
    elif args.stage is not None:
        verdict = check_stage(task, args.stage)
    else:
        verdict = Verdict("ASK_ORGANIZERS", "No stage information was provided.", "Provide --stage or --range, or inspect the source manually.", task)

    if args.json:
        print(json.dumps(asdict(verdict), indent=2, ensure_ascii=False))
    else:
        print(verdict.status)
        print("Reason:", verdict.reason)
        print("Action:", verdict.action)
        print(f"Rules snapshot: {verdict.rules_snapshot}")
        print("Official rules:", verdict.rules_url)

if __name__ == "__main__":
    main()
