---
name: vec-final-phase
description: Walks through the Virtual Embryo test-phase switchover on 20 October 2026, covering the re-read of official pages, test board keys, history rescoring with history-rescore, candidate checks, the two official files per board, and the 2 December deadline. Use on or before 20 October 2026 and through the final phase, when test boards open or a final submission is being chosen.
---

# Final phase: the 20 October switchover

The official pages are authoritative. The checklist in [test-phase-switchover](../../test-phase-switchover/README.md) was prepared on 14 October from those pages, and it lists the items the pages do not state. Re-read these pages on 20 October before acting on any item in this skill:

- https://virtualembryo.ai/challenge/rules
- https://virtualembryo.ai/challenge/timeline
- https://virtualembryo.ai/challenge/data
- https://virtualembryo.ai/challenge/evaluation
- https://virtualembryo.ai/challenge/panels/index.json

Uploads and submissions are irreversible. Stop and ask the user in chat before each one. Approval for one upload does not cover the next.

## Before 20 October (until 19 October)

1. Pin the scorer and confirm it with `python scorer-versions/which_veckit.py`, as in [vec-score-locally](../vec-score-locally/SKILL.md).
2. Set up the disclosure registry for every external source, as in [vec-external-data-guard](../vec-external-data-guard/SKILL.md). Rules section 10: "Every external source must be disclosed with the submission."
3. Follow the rules watch in the community kit (https://github.com/xxx12e/vec-community-kit). The organisers' pages stay authoritative.

## Day 0: 20 October 2026, the test phase starts

1. Read the official pages listed above again, and save dated copies with the team's records.
2. Confirm the test board keys:

   ```bash
   python test-phase-switchover/check_test_contract.py --list
   ```

   Use the keys that appear in index.json. Do not guess them.

3. Rescore the team's history once the validation answers are released. The validation answers for E10.5 T1, E7.5 embryo, E8.5 heart interpolation, E10.5 heart extrapolation and Gata4 are released on this day.
   - The user, not the agent, exports the submissions table. The user opens https://virtualembryo.ai/challenge/account/submissions in their own browser and runs `history-rescore/export_submissions.js` in the console.
   - Fill blank `board` cells by hand. Write `boards.json` with the released files, as described in [history-rescore](../../history-rescore/README.md).
   - Run the rescoring with both protocols and compare the two reports:

     ```bash
     python history-rescore/rescore.py --submissions submissions.csv --search DIR1 DIR2 --boards boards.json --protocol board --seeds 3 --out results/
     python history-rescore/rescore.py --submissions submissions.csv --search DIR1 DIR2 --boards boards.json --protocol full --out results_full/
     ```

   - Read `RESCORE.md` for the local-minus-board difference and the rank correlation per board. With few files these numbers are unstable.
   - Rescoring is an analysis of files already submitted. Use it to choose among predictions, not to compute a test score.
4. Validation ground truth becomes training material on this day. Rules section 10 still names some of those stages as held out for external data. Ask the organisers whether that list stops applying to the released validation stages before using any of them.
5. Test inputs are released without labels. The test answers are never released.

## First week: 20 to 27 October

- Check every candidate against its test board: `python test-phase-switchover/check_test_contract.py PRED.h5ad BOARD_KEY`. This does not replace the organisers' upload check or scorer.
- Freeze candidate files with checksums before the first upload. The community tool `vec-p3-freeze` (https://github.com/random-guy-05/vec-p3-freeze) does this. It is not in this repository and was not verified here.
- Choose the two official files per board. Rules section 11 says 2 official submissions per board for the whole phase. How the captain designates them is not stated, so ask the organisers.
- Read the feedback each upload returns. The timeline says a submission "comes back as a score, not as answers". Whether a per-metric breakdown is returned is not stated.
- Check each external source against the test target windows. Ask the organisers about any source that returns `ASK_ORGANIZERS`.
- Decide the track before the deadline. Rules section 8: "A captain may change track before the final deadline. Doing so retires every score the team has earned."
- Before publishing any result, get prior approval where the FAQ requires it. The FAQ requires approval from Dr. Neil Chi and the data-generating team for any publication or public presentation that uses the data.

## Up to 2 December 2026

- Final submissions are due 2 December 2026. The timeline calls it "the last moment a submission can be made or a final entry nominated. Nothing after this counts."
- Do not leave a final submission to the last hour (rules section 12).
- For Agent Team entries, attach evidence of at least two kinds, one of them the trajectory. State the framework and the model string. See [vec-record-provenance](../vec-record-provenance/SKILL.md). A held entry is not scored until its evidence lands.
- Keep your own copy of every upload with its checksum.

## Reference dates after the deadline

- 4 December 2026: official evaluation starts on the hidden test sets.
- 11 December 2026: winners are announced at NeurIPS. Final rankings come from the hidden test sets, not from the development leaderboard (rules section 13).

## Not stated in the official text

Ask the organisers about these: how the captain designates the two files per board; whether a P3 submission returns a per-metric breakdown; whether the held-out list in rules section 10 stops applying to released validation stages; whether the heart extrapolation window matches the Task 1 window; any evidence deadline after 2 December; and the number of uploads allowed per day.
