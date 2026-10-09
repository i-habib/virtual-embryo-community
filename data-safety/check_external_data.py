#!/usr/bin/env python3
"""Conservative helper for Virtual Embryo external-data eligibility.

This script only automates cases that the published rules make mechanically clear.
Anything involving somite/Theiler conversion, "comparable stage", another allele of a
held-out gene, or a phenocopy should be escalated to the organizers.

Rules Section 10, restatement effective 2026-08-26, checked 2026-10-08
Official source: https://virtualembryo.ai/challenge/rules
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from typing import Optional

RULES_URL = "https://virtualembryo.ai/challenge/rules"
RULES_SNAPSHOT = "Rules Section 10, restatement effective 2026-08-26, checked 2026-10-08"

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

@dataclass(frozen=True)
class StageWindow:
    lo: float
    hi: float
    include_lo: bool
    include_hi: bool

    def contains(self, x: float) -> bool:
        left = x > self.lo or (self.include_lo and x == self.lo)
        right = x < self.hi or (self.include_hi and x == self.hi)
        return left and right

    def intersects_closed_range(self, lo: float, hi: float) -> bool:
        """Whether this protected set intersects the resource's closed [lo, hi] range."""
        left = max(lo, self.lo)
        right = min(hi, self.hi)
        if left < right:
            return True
        if left > right:
            return False
        return self.contains(left)

    def contains_closed_range(self, lo: float, hi: float) -> bool:
        """Whether every point in the resource's closed [lo, hi] range is protected."""
        return self.contains(lo) and self.contains(hi)

PROTECTED_WINDOWS = {
    # Section 10: "External data is excluded from after E9.5 up to and including E13.5."
    # The page states this window for the extrapolation targets without naming a task;
    # the Task 1 extrapolation window is the one attached to a task here.
    "t1": (StageWindow(9.5, 13.5, False, True),),
    # Heart interpolation window only. Section 10 gives no heart-specific extrapolation window.
    "t2-heart": (StageWindow(8.25, 8.75, False, False),),
    # Embryo interpolation is strictly between the released bracketing stages.
    "t2-embryo": (StageWindow(7.25, 8.0, False, False),),
}

# Held-out stages Section 10 names explicitly: "The held-out stages and genotypes are:
# E10.5 and E12.5 for Task 1; E7.5 and E7.75 in the embryo setting and E8.5, E10.5 and
# E12.5 in the heart setting for Task 2".
HELDOUT_STAGES = {
    "t1": (10.5, 12.5),
    "t2-heart": (8.5, 10.5, 12.5),
    "t2-embryo": (7.5, 7.75),
}

# Last stage released for a task whose later stages are not covered by an explicit window.
# Heart data after E9.5 is referred to the organizers rather than classified here.
LAST_RELEASED_STAGE = {
    "t2-heart": 9.5,
}

DISCLOSURE_RULE = (
    'Section 10 says: "Every external source must be disclosed with the submission."'
)
AFTER_E135_RULE = (
    "Data after E13.5 is usable only with its source and stages stated explicitly. "
    'Section 10 says: "Anything after E13.5 may be used, provided the source and its stages '
    'are stated explicitly with the submission."'
)

@dataclass
class Verdict:
    status: str
    reason: str
    action: str
    task: str
    rules_snapshot: str = RULES_SNAPSHOT
    rules_url: str = RULES_URL

def clear_action(base: str, top_stage: float) -> str:
    """Append the disclosure condition to a CLEAR verdict's action text."""
    parts = [base, DISCLOSURE_RULE]
    if top_stage > 13.5:
        parts.append(AFTER_E135_RULE)
    return " ".join(parts)

def canonical_task(task: str) -> str:
    key = task.strip().lower()
    if key not in TASK_ALIASES:
        raise ValueError(f"Unknown task {task!r}. Use t1, t2-heart, t2-embryo, or t3.")
    return TASK_ALIASES[key]

def protected_stage(task: str, stage: float) -> bool:
    """True only for mechanically explicit stage exclusions."""
    return any(w.contains(stage) for w in PROTECTED_WINDOWS.get(task, ()))

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
    if stage in HELDOUT_STAGES.get(task, ()):
        return Verdict(
            "EXCLUDED",
            f"E{stage:g} is a held-out stage for {task}. Section 10 says: "
            '"No measured data from a held-out stage or genotype may be used, by any route."',
            "Do not use measured data from this stage for this task, directly or through a pretrained model or public dataset.",
            task,
        )
    if task in LAST_RELEASED_STAGE and stage > LAST_RELEASED_STAGE[task]:
        return beyond_last_released(task, f"E{stage:g}")
    return Verdict(
        "CLEAR_BY_STAGE_RULE",
        f"E{stage:g} is not inside a mechanically explicit protected stage window for {task}.",
        clear_action(
            "Still check licence, provenance, hidden genotype/condition content, and the current official rules before use.",
            stage,
        ),
        task,
    )

def beyond_last_released(task: str, span: str) -> Verdict:
    """Stages after the last released stage of a task, when no task-specific window applies.

    `span` is the stage label or range being judged, e.g. "E10" or "E9-E10".
    """
    last = LAST_RELEASED_STAGE[task]
    return Verdict(
        "ASK_ORGANIZERS",
        f"{span} reaches past E{last:g}, the last stage released for {task}. Section 10 says: "
        '"Where a held-out stage lies beyond the last released one, as the extrapolation targets do, '
        'everything from the midpoint onwards is treated as held out." It also states: '
        '"External data is excluded from after E9.5 up to and including E13.5." That window is '
        "written for the extrapolation targets without naming a task, so this helper does not apply it to "
        f"{task}.",
        "Ask the organizers before using data from this stage, and quote both passages in the question.",
        task,
    )

def interval_relation(task: str, lo: float, hi: float) -> Verdict:
    """Classify a resource spanning every stage in the closed range [lo, hi].

    The protected challenge intervals have open/closed boundaries. We therefore do exact
    interval intersection rather than probing endpoints or nearby floating-point samples.
    """
    task = canonical_task(task)
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ValueError("Range bounds must be finite.")
    if lo > hi:
        lo, hi = hi, lo
    if task == "t3":
        return Verdict(
            "ASK_ORGANIZERS",
            "Task 3 restrictions are genotype-specific; a stage range alone is insufficient.",
            "Inspect the resource by genotype/condition and ask about any held-out or phenocopying perturbations.",
            task,
        )
    if lo == hi:
        return check_stage(task, lo)

    windows = PROTECTED_WINDOWS[task]

    # A continuous resource range is fully protected only if one protected interval contains
    # the whole thing. Otherwise it contains both permitted and protected stages and must be
    # filtered. This correctly handles [E8.25, E8.75]: both endpoints are permitted while
    # the entire open interval between them is protected.
    fully_protected = any(w.contains_closed_range(lo, hi) for w in windows)
    if fully_protected:
        return Verdict(
            "EXCLUDED",
            f"The supplied range E{lo:g}–E{hi:g} lies entirely inside a protected external-data window for {task}.",
            "Do not use the measured data for this task.",
            task,
        )

    if task in LAST_RELEASED_STAGE and hi > LAST_RELEASED_STAGE[task]:
        return beyond_last_released(task, f"E{lo:g}–E{hi:g}")

    touched = [w for w in windows if w.intersects_closed_range(lo, hi)]
    if not touched:
        return Verdict(
            "CLEAR_BY_STAGE_RULE",
            f"The supplied range E{lo:g}–E{hi:g} does not intersect a mechanically explicit protected stage window for {task}.",
            clear_action("Still inspect all conditions/genotypes, licences, and the latest official rules.", hi),
            task,
        )

    return Verdict(
        "FILTER_REQUIRED",
        f"The resource range E{lo:g}–E{hi:g} contains both permitted and protected stages for {task}.",
        "Remove cells/samples inside every protected window before training and disclose the filtering in the method summary.",
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
        "Still inspect whether the perturbation phenocopies a held-out condition and check the current rules. "
        + DISCLOSURE_RULE,
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
