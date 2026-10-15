# Agent skills for the Virtual Embryo Challenge

An agent skill is a folder with a `SKILL.md` file. The file starts with YAML frontmatter: `name` (the folder name, kebab-case) and `description` (what the skill does and when to use it). The agent reads the description to decide when to load the skill, and the body holds the instructions. A skill may also keep scripts next to it. The format follows the Claude Code skills documentation at https://docs.claude.com/en/docs/claude-code/skills.

These skills tell a coding agent how to work on the challenge with the tools in this repository. The official rules and pages are the source of truth: https://virtualembryo.ai/challenge/rules, https://virtualembryo.ai/challenge/data, https://virtualembryo.ai/challenge/evaluation and https://virtualembryo.ai/challenge/panels/index.json.

## Install

Claude Code loads a skill from `~/.claude/skills/<name>/SKILL.md` for every project, or from `.claude/skills/<name>/SKILL.md` inside one project. Symlink the folder rather than copying it, so the relative links to the repository's tools keep working:

```bash
ln -s "$(pwd)/agent-skills/vec-check-submission" ~/.claude/skills/vec-check-submission
```

Run the tool commands from the repository root. The skills use paths such as `test-phase-switchover/check_test_contract.py` relative to it.

Codex and other agents that read `AGENTS.md`: paste the body of each `SKILL.md` (the text after the closing `---`) into `AGENTS.md`, under a heading with the skill name.

## The eleven skills

| Skill | When to use it | Main tools |
|---|---|---|
| [vec-record-provenance](vec-record-provenance/SKILL.md) | Before, during and after an Agent Team run | `vec_agent_evidence` (community kit), [agent-trace-explorer](../agent-trace-explorer/README.md) |
| [vec-check-submission](vec-check-submission/SKILL.md) | Before any prediction file is uploaded | [test-phase-switchover](../test-phase-switchover/README.md) `check_test_contract.py` |
| [vec-score-locally](vec-score-locally/SKILL.md) | When comparing candidate predictions | [scorer-versions](../scorer-versions/README.md), veckit, [metric-lens](../metric-lens/README.md) |
| [vec-external-data-guard](vec-external-data-guard/SKILL.md) | Before any external dataset is used | [data-safety](../data-safety/README.md) |
| [vec-load-release-data](vec-load-release-data/SKILL.md) | When release or external `.h5ad` files are read or normalised | [count-recovery](../count-recovery/README.md), [panel-normalise](../panel-normalise/README.md) |
| [vec-final-phase](vec-final-phase/SKILL.md) | From 20 October 2026 through the 2 December deadline | [test-phase-switchover](../test-phase-switchover/README.md), [history-rescore](../history-rescore/README.md) |
| [vec-harness-dryrun](vec-harness-dryrun/SKILL.md) | Before locking an Agent Team run, and after every harness or prompt change | [agent-harness-lab](../agent-harness-lab/README.md), [agent-trace-explorer](../agent-trace-explorer/README.md) |
| [vec-context-hygiene](vec-context-hygiene/SKILL.md) | After the last dry run and before the lock | [agent-prelock-audit](../agent-prelock-audit/README.md), `shasum` |
| [vec-submission-ledger](vec-submission-ledger/SKILL.md) | Whenever a prediction is written, scored or uploaded | [vec-score-locally](vec-score-locally/SKILL.md), [scorer-versions](../scorer-versions/README.md), [metric-lens](../metric-lens/README.md) |
| [vec-budget-guard](vec-budget-guard/SKILL.md) | During a locked run with a time or compute budget | [codex-agent-run](../codex-agent-run/README.md), `check_test_contract.py` in [test-phase-switchover](../test-phase-switchover/README.md) |
| [vec-board-genes](vec-board-genes/SKILL.md) | Before writing or fixing any board prediction | `check_test_contract.py` in [test-phase-switchover](../test-phase-switchover/README.md) |


## Check the skills

Run the validator from the repository root. It checks the frontmatter of every skill, that each name matches its folder, that each description is at most 1024 characters, that each file is at most 120 lines, and that every relative link resolves:

```bash
python agent-skills/validate_skills.py
```

Run its tests from the `agent-skills` folder:

```bash
python -m pytest -q
```

Both use only the standard library, except the tests, which need pytest.
