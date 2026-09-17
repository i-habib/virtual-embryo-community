# Virtual Embryo data-safety kit

A conservative helper for one annoying but important part of the challenge: **can I use this external dataset / pretrained model / perturbation source without crossing a held-out-data rule?**

The official rules allow external public data, pretrained models, and published code when licences permit and the source is disclosed. They also prohibit measured held-out stages/genotypes from entering by any route, including through a pretrained model or a general-purpose dataset that contains protected cells.

This package does two small jobs:

1. [`check_external_data.py`](check_external_data.py) handles the stage/genotype cases that are mechanically clear from the published rules.
2. [`render_disclosure.py`](render_disclosure.py) turns a small source registry into a method-summary disclosure section so provenance is recorded while you work instead of reconstructed at the deadline.

## Important limitation

**This is not an official eligibility oracle.**

The challenge rules explicitly rely on biological judgments in some cases: somite/Theiler staging, “comparable stage,” another allele of a held-out gene, and phenocopying perturbations. The script returns `ASK_ORGANIZERS` rather than pretending those cases are machine-decidable.

Rules snapshot used by the checker: **2026-09-16**.

Always re-read the current official rules before a final submission:

https://virtualembryo.ai/challenge/rules

## Quick examples

```bash
# Heart interpolation: strictly between E8.25 and E8.75 is protected.
python check_external_data.py --task t2-heart --stage 8.4

# A general-purpose heart atlas spanning both permitted and protected stages.
python check_external_data.py --task t2-heart --range 8.0 9.0

# T1 external data after E13.5 is outside the explicit extrapolation protection window.
python check_external_data.py --task t1 --stage 14.0

# Held-out Task 3 gene at the held-out stage.
python check_external_data.py --task t3 --gene gata4 --stage 8.75 --allele same

# Another Gata4 allele or a nearby stage is intentionally not guessed.
python check_external_data.py --task t3 --gene gata4 --stage 9.0 --allele other

# Somite/Theiler labels require manual stage mapping.
python check_external_data.py --task t2-embryo --stage-label "6 somites"
```

Possible statuses:

- `EXCLUDED` — the supplied case is inside an explicit protected window / exact held-out condition.
- `FILTER_REQUIRED` — a broader resource crosses both permitted and protected stages; remove the protected part and disclose the filtering.
- `CLEAR_BY_STAGE_RULE` / `CLEAR_BY_NAMED_GENOTYPE_RULE` — the specific mechanical rule checked here does not exclude it. This is **not** a blanket approval.
- `ASK_ORGANIZERS` — the rules require biological or boundary judgment that this script should not invent.

## Stage rules encoded

The helper mirrors the explicit rules published on 2026-09-16:

- **Task 1:** external data after E9.5 through and including E13.5 is excluded. Exactly E9.5 is permitted; after E13.5 is outside that explicit window.
- **Task 2 heart interpolation:** external data strictly between E8.25 and E8.75 is excluded.
- **Task 2 heart extrapolation:** after E9.5 through and including E13.5 is excluded.
- **Task 2 embryo interpolation:** external data strictly between E7.25 and E8.0 is excluded.
- **Task 3:** Gata4 and β-catenin knockouts at E8.75 are held out. Another allele of the same gene at a comparable stage, and phenocopying perturbations, are also treated as held out and therefore return `ASK_ORGANIZERS` unless the exact held-out case is supplied.

A general-purpose resource is not automatically banned merely because it spans a protected stage. The official rules allow removing the protected cells/samples before training, with the removal disclosed. That is why range queries can return `FILTER_REQUIRED`.

## Keep a source registry while you work

Copy:

```bash
cp sources.example.json sources.json
```

and add every external dataset, pretrained model, and published-code source you actually use.

Then:

```bash
python render_disclosure.py sources.json --out external_sources.md
```

The point is not the Markdown formatting. The point is making yourself record:

- exact source URL / DOI
- version or commit
- licence
- stages / conditions contained
- which task used it
- how it entered the method
- what filtering was applied

That gives you a usable method-summary section and makes it much easier to audit a source before final submission.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover interval boundaries that are easy to get subtly wrong, including the fact that E9.5 is allowed while E13.5 is still inside the protected extrapolation window.

Independent community utility. The official rules and organizer answers always override this helper.
