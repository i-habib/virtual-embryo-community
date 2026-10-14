---
name: vec-external-data-guard
description: Checks an external dataset against the challenge's stage and genotype windows with check_external_data.py before any use, stops on EXCLUDED or ASK_ORGANIZERS results, and records each accepted source in a disclosure registry rendered with render_disclosure.py. Use before downloading, loading, or training on any dataset that is not a released challenge file.
---

# Guard external data before use

Rules section 10 (https://virtualembryo.ai/challenge/rules): "Every external source must be disclosed with the submission." Also: "No measured data from a held-out stage or genotype may be used, by any route." A source that passes the mechanical check is still not blanket approval. The checker covers stage windows and named genotypes only, and it does not replace the official rules.

## Steps

1. Write down the source before checking it: stages or conditions, genotype or perturbation, allele, and whether it is a somite or Theiler staging label. Note a non-E-day label, because the checker cannot place it.

2. Run the checker for the task it will serve. Tasks are `t1`, `t2-heart`, `t2-embryo` and `t3`. Use `--stage` for one E-day, or `--range START END` for a resource that spans stages:

   ```bash
   python data-safety/check_external_data.py --task t2-heart --stage 8.4
   python data-safety/check_external_data.py --task t2-heart --range 8.0 9.0
   python data-safety/check_external_data.py --task t3 --gene gata4 --stage 8.75 --allele same
   ```

   Add `--phenocopy` when a source may phenocopy a held-out Task 3 perturbation, and `--json` for machine-readable output. A source labelled with somites or Theiler stages has no E-day to check. Pass its label with `--stage-label` and expect `ASK_ORGANIZERS`.

3. Act on the result:

   - `EXCLUDED`: stop. Do not use the source, and do not use any part of it that falls in the protected window.
   - `ASK_ORGANIZERS`: stop. Ask the user to put the question to the organisers. Do not use the source meanwhile.
   - `FILTER_REQUIRED`: the source spans permitted and protected material. Remove the protected cells first, then run the checker again on the stages that remain.
   - `CLEAR_BY_STAGE_RULE` or `CLEAR_BY_NAMED_GENOTYPE_RULE`: the one mechanical check did not exclude it. Still disclose it and record its filters.

4. Record the accepted source in the registry. Start from `data-safety/sources.example.json`, which is a JSON list. Each entry needs these fields: `name`, `url`, `version`, `license`, `tasks`, `stages_or_conditions`, `used_for`, `filters`. `notes` is optional. Keep the registry in the team's own working folder, not in this repository.

5. Render the disclosure section:

   ```bash
   python data-safety/render_disclosure.py sources.json --out external_sources.md
   ```

## Team rule for model input

Held-out data may serve validation and tiny summary statistics only, never model input. The checker does not enforce this, so check it yourself for every source.

## Limits

- The checker is conservative and does not decide eligibility. Somite and Theiler staging, "comparable stage", other alleles of a held-out gene and phenocopies need biological judgment, and the checker returns `ASK_ORGANIZERS` for them.
- The task windows in the checker follow the rules text as of the checker's last check, 8 October 2026. Re-read https://virtualembryo.ai/challenge/rules before submitting, and again after 20 October.

## Related

- [vec-final-phase](../vec-final-phase/SKILL.md) for the 20 October switchover, where the validation stages become training material.
- [vec-load-release-data](../vec-load-release-data/SKILL.md) for normalising any source that passes this check.
