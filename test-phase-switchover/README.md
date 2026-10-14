# Test-phase switchover checklist

Prepared 14 October 2026 from the official pages as the server returned them that day. The timeline page calls itself "the authoritative schedule", so re-read the official pages on 20 October before acting on any item here. Items marked **Not stated; ask the organisers** do not appear in the official text read for this checklist.

## What was read

- Official pages, text extracted from the server HTML and text present for each: [rules](https://virtualembryo.ai/challenge/rules), [timeline](https://virtualembryo.ai/challenge/timeline), [FAQ](https://virtualembryo.ai/challenge/faq), [data](https://virtualembryo.ai/challenge/data), [tasks](https://virtualembryo.ai/challenge/tasks), [evaluation](https://virtualembryo.ai/challenge/evaluation).
- Not confirmed: https://virtualembryo.ai/challenge returned HTTP 404, so the overview page was not read.
- [panels/index.json](https://virtualembryo.ai/challenge/panels/index.json): five validation boards, with keys T1:val, T2:embryo:val_interp, T2:heart:val_extrap, T2:heart:val_interp and T3:gata4. No test board keys yet. Not stated: the test board keys; they should appear on 20 October.
- Community sources (not official): the tools linked at the end. Where they make a claim about the rules, the official pages were checked instead.

## Test targets

| Task | Test target | Source |
|---|---|---|
| T1 | E12.5, ranked on a hidden E12.5 (extrapolation) | [tasks](https://virtualembryo.ai/challenge/tasks) |
| T2 embryo | E7.75 (interpolation), "E7.75 test" | [tasks](https://virtualembryo.ai/challenge/tasks), [data](https://virtualembryo.ai/challenge/data) |
| T2 heart | E12.5 (extrapolation), "E12.5 extrapolation test" | [tasks](https://virtualembryo.ai/challenge/tasks) |
| T3 | Beta-catenin knockout at E8.75, "the hidden test" | [tasks](https://virtualembryo.ai/challenge/tasks) |

## Checklist

### Now to 19 October (preparation)

- [ ] Follow the rules watch: https://github.com/xxx12e/vec-community-kit/tree/main/rules-watch (community tool; the organisers' pages stay authoritative).
- [ ] Pin the scorer version with [../scorer-versions/](../scorer-versions/). Official text does not name the scorer version the leaderboard runs. The scorer-versions README states that "the version the leaderboard itself runs is not published."
- [ ] Set up the external-source disclosure process with [../data-safety/](../data-safety/). Rules section 10: "Every external source must be disclosed with the submission."

### Day 0: 20 October 2026 (P3 begins)

- [ ] Validation answers are released. Tasks page: "At the start of the final phase the validation answers are released for every task". Then rescore your own history with [../history-rescore/](../history-rescore/). Rules section 10: "Returned scores may be used to choose among predictions, not to compute them."
- [ ] Validation data becomes training material. Data page: "At the final test phase the validation stages are released too, with their answers, so they become training material". Rules section 10 still names those stages among the held-out stages for external data. Not stated; ask the organisers whether that list stops applying to the released validation stages.
- [ ] Test inputs are released without labels. Timeline: "The test inputs are released without their labels ... the test answers never are."
- [ ] Test leaderboard opens. Run `python check_test_contract.py --list` (in this folder) and confirm the test board keys in index.json.
- [ ] Re-check each test board's cell bounds. Data page: "Machine-readable index, including cell limits and the required obsm keys: index.json."

### First week (20 to 27 October)

- [ ] Check every candidate file locally against its test board: `python check_test_contract.py PRED.h5ad BOARD_KEY`. Rules section 11: "Format checks are unlimited in every phase and spend nothing." The checker does not replace the organisers' upload check or scorer.
- [ ] Freeze the candidate files with checksums before the first upload, using [random-guy-05/vec-p3-freeze](https://github.com/random-guy-05/vec-p3-freeze) (community tool). Rules section 11: "Each is scored and published when it is made, and cannot be withdrawn."
- [ ] Choose the two official files per board. Rules section 11: "2 official submissions per board, for the whole phase rather than per day." A planning note said up to two per task; the official limit is per board, so T2 has two test boards and the limit applies to each. How the captain designates a file: Not stated; ask the organisers. The timeline mentions a "final entry nominated", but no procedure appears on the pages read.
- [ ] Confirm what feedback a P3 submission returns. A planning note says "no performance feedback". The official text says a test submission "comes back as a score, not as answers" (timeline page), and rules section 11 says each is "scored and published when it is made". Whether a per-metric breakdown is returned: Not stated; ask the organisers.
- [ ] Check each external source against the test target windows (table below), using [../data-safety/](../data-safety/) for the mechanical checks. Ask the organisers about any source that the tool returns as ASK_ORGANIZERS.
- [ ] Decide the track before the deadline. Rules section 8: "A captain may change track before the final deadline. Doing so retires every score the team has earned."
- [ ] Before publishing any result, note the approval requirement. FAQ: "any use of the data in a publication or public presentation must receive prior approval from Dr. Neil Chi and the data-generating team."

### Before the deadline (until 2 December 2026)

- [ ] Final submissions are due on 2 December 2026. Timeline: "The last moment a submission can be made or a final entry nominated. Nothing after this counts, in either track." Rules section 17: "The Organisers may extend a deadline; a deadline is never brought forward without notice." Rules section 12: "Do not leave a final submission to the last hour of a deadline."
- [ ] Keep your own copy of every upload with its checksum. Rules section 12: "Keep your own copy of everything you submit."
- [ ] Agent Team entries: a submission is held until at least two distinct kinds of evidence are attached, one of them the trajectory (rules section 9). "A final entry nominated for prizes must carry its evidence." Evidence deadline beyond 2 December: Not stated; ask the organisers.
- [ ] Agent Team entries: state the framework and the model string actually run with each submission (rules section 9).
- [ ] Rescoring is possible while the phase is open. FAQ: "after a phase closes the board is fixed, so a problem is worth reporting the day you see it rather than at the end."
- [ ] Daily limits in the final phase: none beyond the per-board total. Rules section 11: "every upload counts toward a separate daily upload limit, which exists to bound storage rather than to limit scoring." The number of uploads per day: Not stated. A single prediction file may not exceed 1200 MB (rules section 11).

### After the deadline (reference)

- [ ] 4 December 2026: official evaluation starts on the hidden test sets. Timeline: "Agent Team entries are checked against the evidence attached to them."
- [ ] 11 December 2026: winners announced at NeurIPS. Rules section 13: "Final rankings are determined by the hidden test sets, not by the development leaderboard."
- [ ] Winners: a written method report within 14 days of notification (rules section 15). Code may be requested for verification (rules section 14).

## External data windows for the test targets

These are the windows stated in the rules, FAQ and data page. Where the official text does not state the window, the row says so.

- **T1 E12.5 (extrapolation).** Rules section 10: "External data is excluded from after E9.5 up to and including E13.5. E10.5 and E12.5, the validation and test targets themselves, are excluded absolutely. Anything after E13.5 may be used, provided the source and its stages are stated explicitly with the submission." Data measured at exactly E9.5 is permitted. Data measured at exactly E13.5 is not.
- **T2 heart E12.5 (extrapolation).** The rules say "For the extrapolation targets the window is stated outright rather than derived". The FAQ and data page say "For the Task 1 extrapolation targets". Whether the E9.5 to E13.5 window applies to the heart extrapolation target: Not stated; ask the organisers.
- **T2 embryo E7.75 (interpolation).** Rules section 10: "external data may not be used if it stages strictly between the two released stages that bracket a held-out one. In Task 2 that means ... embryo data strictly between E7.25 and E8.0." The bracketing stages are permitted. The E7.5 validation stage is released at P3 (data page); the rules still list E7.5 and E7.75 as held out for external data.
- **T3 beta-catenin at E8.75.** Rules section 10: "data from the held-out knockouts, from another allele of the same gene at a comparable stage, or from a perturbation that phenocopies them, is treated as the held-out condition." No numeric window is stated. Whether a given source is comparable: Not stated; ask the organisers.
- **Any test target.** Rules section 10: "A general-purpose resource that happens to span a held-out stage is not banned outright: the cells inside the window must be removed before training." Rules section 10 also states: "No measured data from a held-out stage or genotype may be used, by any route".

## Related tools

- [../history-rescore/](../history-rescore/): rescores your submitted files locally once the validation answers are out.
- [../scorer-versions/](../scorer-versions/): identifies which veckit scorer code is installed. Pin the version you use.
- [../data-safety/](../data-safety/): checks external sources against the rules' stage windows and renders the disclosure text.
- [check_test_contract.py](check_test_contract.py) (this folder): re-checks a prediction against any board in index.json. Tests: `python -m pytest -q` in this folder.
- Community validators, which do more than this checker: [vec_submit_check](https://github.com/xxx12e/vec-community-kit/tree/main/vec_submit_check) in xxx12e/vec-community-kit, and [gh-dv-openclaw/vec-submit-check](https://github.com/gh-dv-openclaw/vec-submit-check). Both check the log1p(CP10k) scale that the checker here does not.
- [random-guy-05/vec-splitforge](https://github.com/random-guy-05/vec-splitforge): builds pseudo-validation splits with a P3 preview mode. Its P3 windows are its author's reading, not official text.
- [random-guy-05/vec-p3-freeze](https://github.com/random-guy-05/vec-p3-freeze): freezes candidate files with checksums and manages the two slots per board.
- [xxx12e/vec-community-kit](https://github.com/xxx12e/vec-community-kit): tutorial section 11 covers the final-phase changes and the held-out-list question in more detail.

## Not stated in the official text

- How the captain designates the two official files per board.
- Whether a P3 submission returns a per-metric breakdown.
- Whether the held-out list in rules section 10 stops applying to released validation stages.
- Whether the heart extrapolation window matches the Task 1 window.
- A separate evidence deadline for Agent Team entries beyond the 2 December nomination.
- The number of uploads allowed per day.
- The test board keys and their cell bounds, which appear in index.json on 20 October.
