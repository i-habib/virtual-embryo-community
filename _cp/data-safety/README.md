# Virtual Embryo data-safety kit

A small, conservative helper for external-data eligibility. The question it tries to answer is narrow: **does this source cross one of the challenge rules that can be checked mechanically?**

It does two things:

- [`check_external_data.py`](check_external_data.py) checks explicit stage windows and exact named Task 3 conditions.
- [`render_disclosure.py`](render_disclosure.py) turns a source registry into a method-report disclosure section.

It is **not** an eligibility oracle. Somite/Theiler staging, “comparable stage,” another allele of a held-out gene, and phenocopying perturbations require biological judgment. Those cases return `ASK_ORGANIZERS`.

Rules snapshot: **2026-09-16**. Re-read the [official rules](https://virtualembryo.ai/challenge/rules) before submitting.

## Examples

```bash
# Inside the protected Task 2 heart interpolation window
python check_external_data.py --task t2-heart --stage 8.4

# A broad atlas crossing both legal and protected stages
python check_external_data.py --task t2-heart --range 8.0 9.0

# Exact held-out Task 3 condition
python check_external_data.py --task t3 --gene gata4 --stage 8.75 --allele same

# An ambiguous allele/stage case
python check_external_data.py --task t3 --gene gata4 --stage 9.0 --allele other
```

The possible outputs are deliberately plain:

- `EXCLUDED` — the supplied case lies inside an explicit protected window or exact held-out condition.
- `FILTER_REQUIRED` — the resource spans both permitted and protected material.
- `CLEAR_BY_STAGE_RULE` / `CLEAR_BY_NAMED_GENOTYPE_RULE` — that one mechanical check did not exclude it. This is not blanket approval.
- `ASK_ORGANIZERS` — the rule cannot be resolved responsibly from the supplied metadata.

## Stage logic encoded

As of the rules snapshot:

- **T1:** `(E9.5, E13.5]` is protected for external extrapolation data.
- **T2 heart interpolation:** `(E8.25, E8.75)` is protected.
- **T2 heart extrapolation:** `(E9.5, E13.5]` is protected.
- **T2 embryo interpolation:** `(E7.25, E8.0)` is protected.
- **T3:** Gata4 and β-catenin knockouts at E8.75 are held out. Related alleles/comparable stages and phenocopies are not guessed by the script.

The interval notation matters. An early version of this tool got the “legal endpoints around a protected open interval” case wrong; the current implementation uses explicit open/closed interval intersection and has regression tests for those boundaries.

## Keep the disclosure while you work

Start from [`sources.example.json`](sources.example.json) and record the exact source, version, licence, stages/conditions, task, role in the method, and filtering. Then:

```bash
python render_disclosure.py sources.json --out external_sources.md
```

The generated Markdown is not the important part. Having the provenance written down before the deadline is.

## Tests

```bash
python -m unittest discover -s tests -v
```

Independent community utility. Organizer guidance and the current official rules always override this checker.
