#!/usr/bin/env python3
"""Pre-lock contamination audit for a Virtual Embryo Agent Team run.

Given a workspace and the agent CLI that will run in it, the audit:

1. inventories the context files that CLI loads automatically (project and
   user instruction files, imports, auto memory), with sizes and SHA-256 hashes;
2. scans the workspace, those context files, the auto memory directory, the
   git history, optional extra paths and the CLI's own session logs for
   steering or leak signals;
3. writes a lock record (JSON) and a Markdown report, and exits 1 when any
   BLOCK finding exists.

Standard library only. Secret-like values are never printed or stored; the
report records only that such a value exists and where.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Optional

SCHEMA = "prelock_audit/1"
CLI_CHOICES = ("claude", "codex", "opencode", "generic")
RULE_SOURCES = {
    "claude": "https://code.claude.com/docs/en/memory",
    "codex": "https://learn.chatgpt.com/docs/agent-configuration/agents-md",
    "opencode": "https://opencode.ai/docs/rules/",
    "generic": "union of the claude, codex and opencode rules plus GEMINI.md; every candidate is treated as loaded",
}
# "auto" and "on-demand" and "assumed" entries are in the agent's context;
# "not loaded" entries are only files the agent can read with its tools.
LOADED_LABELS = ("auto", "on-demand", "assumed")
TEXT_MAX_BYTES = 5 * 1024 * 1024
IMPORT_MAX_HOPS = 4
WITHHELD_SECRET = "[line withheld: secret-like value]"
REDACTED = "[excerpt withheld by --redact-excerpts]"
ENV_FLAGS = (
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "OPENCODE_DISABLE_CLAUDE_CODE",
    "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT",
    "XDG_CONFIG_HOME",
)
SHELL_HISTORY_NAMES = (".zsh_history", ".bash_history")

SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".civenv",
    ".pytest_cache", ".ipynb_checkpoints", ".mypy_cache", ".tox",
})
DATA_EXT = frozenset({
    ".csv", ".tsv", ".txt", ".json", ".npy", ".npz", ".h5", ".h5ad", ".hdf5",
    ".parquet", ".pkl", ".pickle", ".zarr", ".zip", ".gz", ".tar", ".feather",
    ".loom", ".rds", ".mtx", ".xlsx", ".xls",
})
CODE_EXT = frozenset({
    ".py", ".r", ".ipynb", ".js", ".ts", ".sh", ".cfg", ".ini", ".toml",
})
ENV_TEMPLATE_SUFFIXES = frozenset({".example", ".sample", ".template", ".dist"})

# Held-out stages and genotypes, from the challenge rules (fetched 2026-10-14):
# E10.5 and E12.5 (Task 1); E7.5 and E7.75 (Task 2 embryo); E8.5, E10.5 and
# E12.5 (Task 2 heart); Gata4 and beta-catenin knockouts at E8.75 (Task 3).
STAGE_RE = re.compile(r"(?<![A-Za-z0-9])E(?:7\.5|7\.75|8\.5|8\.75|10\.5|12\.5)(?![0-9])")
GENO_RE = re.compile(r"gata4|ctnnb1|beta-?catenin|\u03b2-?catenin", re.I)
GENO_KO_RE = re.compile(r"knock-?out|(?<![a-z])ko(?![a-z])|E8\.75", re.I)
SCORE_WORD_RE = re.compile(
    r"leaderboard|\bboard\b|\blb\b|\bscores?\b|\bskill\b|\bheadline\b|\bsubmitted\b|\bsubmissions?\b",
    re.I,
)
# A decimal such as 74.9 or 0.123 (a sentence-final period is allowed), but not a version such as 0.4.1.
DECIMAL_RE = re.compile(r"(?<!\d)(?<!\d\.)\d{1,4}\.\d{1,4}(?!\d)(?!\.\d)")
SCORE_NAME_RE = re.compile(
    r"leaderboard|(?<![a-z])submissions(?![a-z])|(?<![a-z])scores?(?![a-z])|headline",
    re.I,
)
STAGE_NAME_RE = re.compile(r"(?<![a-z0-9])e(?:7\.5|7\.75|8\.5|8\.75|10\.5|12\.5)(?![0-9])", re.I)
ANSWER_NAME_RE = re.compile(
    r"truth|heldout|held[_-]?out|holdout|val[_-]?(?:answers?|targets?|truth|labels?)"
    r"|(?<![a-z])answers?(?![a-z])|validation[_-]?(?:targets?|truth)",
    re.I,
)
SECRET_PATTERNS = (
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("sk- style API key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    (
        "quoted credential assignment",
        re.compile(r"(?i)\b(api[_-]?key|secret|token|passw(?:or)?d|access[_-]?key)\b\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']"),
    ),
)
ENV_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*\S)?\s*$")
IMPORT_RE = re.compile(r"(?<![\w`])@((?:~/|\.{1,2}/|/)?[^\s`'\"]+?\.md)(?=\s|$)")

LIMITS = [
    "Pattern rules produce false positives and misses. A clean result shows that these rules found nothing, not that nothing is present.",
    "The audit does not check external datasets against the rules' nearness test (a dataset closer to a held-out stage than to the nearest released stage).",
    "Codex config.toml is not parsed, so project_doc_fallback_filenames and project_doc_max_bytes are not applied.",
    "Claude settings are read only for autoMemoryEnabled and autoMemoryDirectory. Other settings, managed policy files and organisation CLAUDE.md files are not inventoried.",
    "Auto memory is matched by a path key derived from the git root (the path with separators replaced by hyphens). If the CLI derives the key differently, pass --memory-dir.",
    "Git history is checked by file name only. Contents of deleted files are not read.",
    "This script does not launch the agent and does not enforce anything. Enforcement comes from the launcher (for example permission deny rules or a clean worktree).",
    "A lock record shows what was on disk and what the CLI was expected to load at the time of the audit. It does not prove what the agent later read.",
]


# --------------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------------

@dataclass
class Entry:
    """A context or memory file the CLI loads, or may load, for this workspace."""

    path: str
    rule: str
    loaded: str  # auto | on-demand | assumed | not loaded
    bytes: int
    sha256: str
    imported_from: Optional[str] = None


@dataclass
class Finding:
    verdict: str  # BLOCK | REVIEW | INFO
    category: str
    path: str
    line: Optional[int]
    detail: str
    excerpt: Optional[str]
    in_auto_loaded_context: bool


@dataclass
class Homes:
    home: Path
    claude_dir: Path
    codex_home: Path
    opencode_dir: Path


@dataclass
class Inventory:
    entries: list = field(default_factory=list)
    absent: list = field(default_factory=list)
    _seen: dict = field(default_factory=dict)

    def add(self, path: Path, rule: str, loaded: str, imported_from: Optional[str] = None) -> Entry:
        key = str(path.resolve())
        rank = {"auto": 3, "on-demand": 2, "assumed": 2, "not loaded": 0}
        if key in self._seen:
            existing = self._seen[key]
            if rank[loaded] > rank[existing.loaded]:
                existing.loaded = loaded
                existing.rule = rule
            return existing
        try:
            size, digest = path.stat().st_size, sha256_file(path)
        except OSError:
            size, digest = -1, "unreadable"
        entry = Entry(
            path=str(path),
            rule=rule,
            loaded=loaded,
            bytes=size,
            sha256=digest,
            imported_from=imported_from,
        )
        self.entries.append(entry)
        self._seen[key] = entry
        return entry

    def loaded_keys(self) -> set:
        return {str(Path(e.path).resolve()) for e in self.entries if e.loaded in LOADED_LABELS}


class Collector:
    def __init__(self, redact: bool):
        self.redact = redact
        self.findings: list = []

    def add(self, verdict: str, category: str, path: str, line: Optional[int], detail: str,
            excerpt: Optional[str], in_ctx: bool) -> None:
        if excerpt is not None and self.redact and excerpt != WITHHELD_SECRET:
            excerpt = REDACTED
        self.findings.append(Finding(verdict, category, path, line, detail, excerpt, in_ctx))


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def truthy(value: Optional[str]) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def verdict_for(in_ctx: bool) -> str:
    return "BLOCK" if in_ctx else "REVIEW"


def window(text: str, start: int, width: int = 160) -> str:
    text = text.replace("\t", " ").rstrip()
    if len(text) <= width:
        return text.strip()
    a = max(0, start - width // 2)
    b = min(len(text), a + width)
    a = max(0, b - width)
    return ("..." if a else "") + text[a:b] + ("..." if b < len(text) else "")


def secret_kind(line: str) -> Optional[str]:
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(line):
            return label
    return None


def read_text_if_small(path: Path) -> Optional[str]:
    """Return decoded text, or None for binary, oversize or unreadable files."""
    try:
        if path.stat().st_size > TEXT_MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def git_root_for(start: Path) -> Optional[Path]:
    """Nearest directory holding .git, following worktree pointers to the main repo."""
    for directory in [start] + list(start.parents):
        dot = directory / ".git"
        if dot.is_dir():
            return directory
        if dot.is_file():
            try:
                match = re.match(r"gitdir:\s*(.+)", dot.read_text(encoding="utf-8").strip())
            except OSError:
                return directory
            if not match:
                return directory
            gitdir = Path(match.group(1).strip())
            if not gitdir.is_absolute():
                gitdir = (directory / gitdir)
            if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
                return gitdir.parents[2]
            return directory
    return None


def chain_root_to_ws(ws: Path, root: Path) -> list:
    """Directories from the project root down to the workspace, root first."""
    dirs = [ws] + list(ws.parents)
    dirs = dirs[: dirs.index(root) + 1] if root in dirs else [ws]
    return list(reversed(dirs))


def iter_files(root: Path, skip: frozenset) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and str((here / d).resolve()) not in skip
        )
        for name in sorted(filenames):
            path = here / name
            if path.is_file():
                yield path


def is_below(path: Path, ancestor: Path) -> bool:
    return ancestor in path.parents


def is_env_file(path: Path) -> bool:
    return path.name.startswith(".env") and path.suffix.lower() not in ENV_TEMPLATE_SUFFIXES


def resolve_homes(home_arg: Optional[str], environ: Mapping) -> Homes:
    """Locate CLI homes. Environment overrides apply only when no home is given."""
    use_env = home_arg is None
    home = Path(home_arg).expanduser().resolve() if home_arg else Path.home().resolve()
    claude_env = environ.get("CLAUDE_CONFIG_DIR") if use_env else None
    codex_env = environ.get("CODEX_HOME") if use_env else None
    xdg = environ.get("XDG_CONFIG_HOME") if use_env else None
    claude_dir = Path(claude_env).expanduser().resolve() if claude_env else home / ".claude"
    codex_home = Path(codex_env).expanduser().resolve() if codex_env else home / ".codex"
    opencode_dir = (Path(xdg).expanduser().resolve() / "opencode") if xdg else (home / ".config" / "opencode")
    return Homes(home, claude_dir, codex_home, opencode_dir)


def first_nonempty(directory: Path, names: tuple) -> Optional[Path]:
    for name in names:
        candidate = directory / name
        try:
            if candidate.is_file() and candidate.read_bytes().strip():
                return candidate
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------
# Inventory: what each CLI loads
# --------------------------------------------------------------------------

def _label(assume: bool, loaded: str) -> str:
    return "assumed" if assume else loaded


def build_claude(inv: Inventory, ws: Path, root: Path, homes: Homes, environ: Mapping,
                 assume: bool, memory_override: Optional[Path]) -> dict:
    """Claude Code: CLAUDE.md files in cwd and ancestors, user rules, AGENTS.md fallback, auto memory."""
    ancestors = [ws] + list(ws.parents)
    user_claude = homes.claude_dir / "CLAUDE.md"
    if user_claude.is_file():
        inv.add(user_claude, "user CLAUDE.md (~/.claude), loaded every session", _label(assume, "auto"))
    else:
        inv.absent.append(str(user_claude))
    user_rules = homes.claude_dir / "rules"
    if user_rules.is_dir():
        for rules in sorted(user_rules.rglob("*.md")):
            inv.add(rules, "user rules (~/.claude/rules)", _label(assume, "auto"))

    found_claude_md = False
    for directory in ancestors:
        for rel, rule in (("CLAUDE.md", "project CLAUDE.md"),
                          ("CLAUDE.local.md", "project CLAUDE.local.md"),
                          (".claude/CLAUDE.md", "project .claude/CLAUDE.md")):
            candidate = directory / rel
            if candidate.is_file():
                inv.add(candidate, f"{rule} in cwd or ancestor", _label(assume, "auto"))
                found_claude_md = True
            elif directory == ws:
                inv.absent.append(str(candidate))
        rules_dir = directory / ".claude" / "rules"
        if rules_dir.is_dir():
            for rules in sorted(rules_dir.rglob("*.md")):
                inv.add(rules, "project rules (.claude/rules) in cwd or ancestor", _label(assume, "auto"))

    # AGENTS.md is read by Claude Code only when no CLAUDE.md (of the three
    # kinds above) exists in the cwd or an ancestor. ~/.claude/CLAUDE.md and
    # rules do not count for that check.
    for directory in ancestors:
        for rel in ("AGENTS.md", ".claude/AGENTS.md"):
            candidate = directory / rel
            if not candidate.is_file():
                continue
            if assume or not found_claude_md:
                inv.add(candidate, "AGENTS.md read because no CLAUDE.md is in cwd or above",
                        _label(assume, "auto"))
            else:
                inv.add(candidate, "AGENTS.md present but not read (CLAUDE.md found above)", "not loaded")

    memory = claude_memory(ws, root, homes, environ, memory_override)
    memory_dir = memory["directory"]
    if memory_dir is not None and memory_dir.is_dir():
        enabled = memory["enabled"] or assume
        for path in sorted(p for p in iter_files(memory_dir, frozenset())):
            loaded = _label(assume, "auto" if enabled else "not loaded")
            inv.add(path, "auto memory (MEMORY.md is loaded; topic files load on demand)", loaded)
    return memory


def claude_memory(ws: Path, root: Path, homes: Homes, environ: Mapping,
                  memory_override: Optional[Path]) -> dict:
    settings_files = [
        ("local settings", ws / ".claude" / "settings.local.json"),
        ("project settings", ws / ".claude" / "settings.json"),
        ("user settings", homes.claude_dir / "settings.json"),
    ]
    enabled_setting = None
    directory_setting = None
    for _, path in settings_files:
        data = _read_json(path)
        if enabled_setting is None and "autoMemoryEnabled" in data:
            enabled_setting = data["autoMemoryEnabled"]
        if directory_setting is None and isinstance(data.get("autoMemoryDirectory"), str):
            directory_setting = data["autoMemoryDirectory"]

    key = str(root).replace(os.sep, "-")
    project_dir = homes.claude_dir / "projects" / key
    if memory_override is not None:
        directory = memory_override
    elif directory_setting and (directory_setting.startswith("/") or directory_setting.startswith("~/")):
        directory = Path(directory_setting).expanduser()
    else:
        directory = project_dir / "memory"

    if truthy(environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")):
        enabled, reason = False, "CLAUDE_CODE_DISABLE_AUTO_MEMORY is set"
    elif enabled_setting is False:
        enabled, reason = False, "autoMemoryEnabled is false in settings"
    else:
        enabled, reason = True, "enabled"

    other = []
    projects = homes.claude_dir / "projects"
    if projects.is_dir():
        other = sorted(p.name for p in projects.iterdir() if p.is_dir() and p.name != key)
    return {
        "enabled": enabled,
        "reason": reason,
        "directory": directory,
        "project_dir": project_dir if project_dir.is_dir() else None,
        "project_key": key,
        "other_project_dirs": other,
    }


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def build_codex(inv: Inventory, ws: Path, root: Path, homes: Homes, assume: bool) -> None:
    """Codex: first non-empty AGENTS.override.md or AGENTS.md in CODEX_HOME, then one per directory from project root to cwd."""
    names = ("AGENTS.override.md", "AGENTS.md")
    global_file = first_nonempty(homes.codex_home, names)
    if global_file is not None:
        inv.add(global_file, "codex global instructions (CODEX_HOME, override wins)", _label(assume, "auto"))
    else:
        inv.absent.extend(str(homes.codex_home / n) for n in names)
    for directory in chain_root_to_ws(ws, root):
        chosen = first_nonempty(directory, names)
        if chosen is not None:
            inv.add(chosen, f"codex project instructions in {directory}", _label(assume, "auto"))


def build_opencode(inv: Inventory, ws: Path, root: Path, homes: Homes, environ: Mapping,
                   assume: bool) -> None:
    """OpenCode: AGENTS.md at global and project level; Claude Code files as fallbacks."""
    disable_all = (not assume) and truthy(environ.get("OPENCODE_DISABLE_CLAUDE_CODE"))
    disable_global_claude = (not assume) and truthy(environ.get("OPENCODE_DISABLE_CLAUDE_CODE_PROMPT"))

    global_agents = homes.opencode_dir / "AGENTS.md"
    if global_agents.is_file():
        inv.add(global_agents, "opencode global AGENTS.md", _label(assume, "auto"))
    elif not (disable_all or disable_global_claude) and (homes.claude_dir / "CLAUDE.md").is_file():
        inv.add(homes.claude_dir / "CLAUDE.md",
                "opencode fallback: ~/.claude/CLAUDE.md (no opencode global AGENTS.md)",
                _label(assume, "auto"))

    chain = chain_root_to_ws(ws, root)
    project_agents = [d / "AGENTS.md" for d in chain if (d / "AGENTS.md").is_file()]
    for path in project_agents:
        inv.add(path, "opencode project AGENTS.md", _label(assume, "auto"))
    if not project_agents and not disable_all:
        for directory in chain:
            if (directory / "CLAUDE.md").is_file():
                inv.add(directory / "CLAUDE.md", "opencode fallback: project CLAUDE.md (no AGENTS.md)",
                        _label(assume, "auto"))


def build_generic_extra(inv: Inventory, ws: Path, root: Path, homes: Homes) -> None:
    for directory in chain_root_to_ws(ws, root):
        candidate = directory / "GEMINI.md"
        if candidate.is_file():
            inv.add(candidate, "GEMINI.md in project chain (generic union)", "assumed")
    gemini_home = homes.home / ".gemini" / "GEMINI.md"
    if gemini_home.is_file():
        inv.add(gemini_home, "GEMINI.md in home (generic union)", "assumed")


def subdirectory_context(inv: Inventory, ws: Path, names: tuple, rule: str, loaded: str) -> None:
    """Files below the cwd load only when the agent opens something in that subtree."""
    for path in iter_files(ws, frozenset()):
        if path.name in names or (path.suffix == ".md" and ".claude" in path.parts and "rules" in path.parts):
            if is_below(path, ws) and path.parent != ws:
                inv.add(path, rule, loaded)


def follow_imports(inv: Inventory, homes: Homes) -> None:
    """Expand @path.md imports from loaded files (depth limit: IMPORT_MAX_HOPS)."""
    frontier = [(e, 0) for e in list(inv.entries) if e.loaded in LOADED_LABELS]
    while frontier:
        entry, depth = frontier.pop(0)
        if depth >= IMPORT_MAX_HOPS:
            continue
        text = read_text_if_small(Path(entry.path))
        if text is None:
            continue
        for target in parse_imports(text):
            if target.startswith("~/"):
                resolved = homes.home / target[2:]
            elif target.startswith("/"):
                resolved = Path(target)
            else:
                resolved = Path(entry.path).parent / target
            if resolved.is_file():
                child = inv.add(resolved, f"import from {Path(entry.path).name}", entry.loaded,
                                imported_from=entry.path)
                frontier.append((child, depth + 1))


def parse_imports(text: str) -> list:
    targets = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        targets.extend(m.group(1) for m in IMPORT_RE.finditer(line))
    return targets


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

def name_findings(col: Collector, display: str, path: Path, in_ctx: bool, git_commit: Optional[str] = None) -> None:
    base = path.name
    suffix = path.suffix.lower()
    is_data = suffix in DATA_EXT
    is_code = suffix in CODE_EXT
    prefix = f"git history {git_commit}: " if git_commit else ""
    verdict = "REVIEW" if git_commit else verdict_for(in_ctx)

    stage = STAGE_NAME_RE.search(base)
    geno = GENO_RE.search(base) and GENO_KO_RE.search(base)
    if (stage or geno) and (is_data or in_ctx):
        col.add(verdict, "held-out marker in file name", display, None,
                prefix + "file name carries a held-out stage or knockout marker", base, in_ctx)
    if SCORE_NAME_RE.search(base) and not is_code:
        col.add(verdict, "score or submission file name", display, None,
                prefix + "file name suggests leaderboard, submissions or scores", base, in_ctx)
    if is_data and ANSWER_NAME_RE.search(base):
        col.add(verdict, "answer or cached target file name", display, None,
                prefix + "data file name suggests validation answers or cached targets", base, in_ctx)


def scan_content(col: Collector, display: str, text: str, in_ctx: bool, is_code: bool) -> None:
    stage_first = None
    stage_count = 0
    note_first = None
    note_count = 0
    for number, line in enumerate(text.splitlines(), 1):
        kind = secret_kind(line)
        if kind:
            col.add("REVIEW", "secret-like value", display, number,
                    f"{kind} present (value not shown; rotate it if it is live)",
                    WITHHELD_SECRET, in_ctx)
            continue
        numeric = DECIMAL_RE.search(STAGE_RE.sub(" ", line))
        word = SCORE_WORD_RE.search(line)
        stage = STAGE_RE.search(line)
        geno = GENO_RE.search(line) and GENO_KO_RE.search(line)
        if word and numeric:
            col.add(verdict_for(in_ctx), "score-like number",
                    display, number,
                    "decimal number on a line with a board or score word",
                    window(line, word.start()), in_ctx)
        if (stage or geno) and (word or numeric):
            col.add(verdict_for(in_ctx), "held-out marker with numbers",
                    display, number,
                    "held-out stage or genotype on a line with a number or score word",
                    window(line, (stage or geno).start()), in_ctx)
        elif stage or geno:
            if stage_first is None:
                stage_first = (number, line, (stage or geno).start())
            stage_count += 1
        if word and not numeric and not is_code:
            if note_first is None:
                note_first = (number, line, word.start())
            note_count += 1
    if stage_first is not None:
        number, line, start = stage_first
        verdict = "REVIEW" if (in_ctx or not is_code) else "INFO"
        col.add(verdict, "held-out marker named",
                display, number,
                f"{stage_count} line(s) name a held-out stage or genotype without numbers",
                window(line, start), in_ctx)
    if note_first is not None:
        number, line, start = note_first
        col.add("REVIEW", "steering note without numbers",
                display, number,
                f"{note_count} line(s) mention board or score words in a non-code file",
                window(line, start), in_ctx)


def scan_env_file(col: Collector, display: str, text: str, in_ctx: bool) -> None:
    for number, line in enumerate(text.splitlines(), 1):
        match = ENV_ASSIGN_RE.match(line)
        if match and match.group(2) and match.group(2).strip("\"' "):
            col.add("REVIEW", "secret-like value",
                    display, number,
                    f"environment assignment {match.group(1)} present (value not shown)",
                    f"{match.group(1)}=[value withheld]", in_ctx)


def git_history_names(ws: Path) -> tuple:
    """Return (commit->path list, status). Status is 'read' or a reason it was skipped."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(ws), "log", "--all", "--name-only", "--format=COMMIT %H"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"skipped: {type(exc).__name__}"
    if proc.returncode != 0:
        return [], "skipped: not a git repository or git failed"
    pairs = []
    commit = None
    for line in proc.stdout.splitlines():
        if line.startswith("COMMIT "):
            commit = line[7:15]
        elif line.strip() and commit:
            pairs.append((commit, line.strip()))
    return pairs, "read"


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def run_audit(ws: Path, cli: str, *, home: Optional[str] = None, environ: Optional[Mapping] = None,
              memory_dir: Optional[Path] = None, extra_scan: Iterable = (), use_git: bool = True,
              redact: bool = False, skip: frozenset = frozenset(), now: Optional[str] = None) -> tuple:
    if cli not in CLI_CHOICES:
        raise ValueError(f"unknown cli: {cli}")
    environ = dict(os.environ) if environ is None else dict(environ)
    ws = ws.resolve()
    homes = resolve_homes(home, environ)
    root = git_root_for(ws) or ws
    assume = cli == "generic"
    inv = Inventory()
    memory: dict = {}

    if cli in ("claude", "generic"):
        memory = build_claude(inv, ws, root, homes, environ, assume,
                              memory_dir.resolve() if memory_dir else None)
        subdirectory_context(inv, ws, ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"),
                             "CLAUDE.md or AGENTS.md below cwd (read on demand)", _label(assume, "on-demand"))
    if cli in ("codex", "generic"):
        build_codex(inv, ws, root, homes, assume)
    if cli in ("opencode", "generic"):
        build_opencode(inv, ws, root, homes, environ, assume)
        subdirectory_context(inv, ws, ("AGENTS.md",),
                             "AGENTS.md below project root (read on demand)", _label(assume, "on-demand"))
    if cli == "generic":
        build_generic_extra(inv, ws, root, homes)
    if cli in ("claude", "generic"):
        # Only Claude Code expands @path imports in its instruction files.
        follow_imports(inv, homes)

    col = Collector(redact)
    ctx_keys = inv.loaded_keys()
    targets: dict = {}

    def target(path: Path, in_ctx: bool) -> None:
        key = str(path.resolve())
        if key not in targets:
            targets[key] = (path, in_ctx)
        elif in_ctx:
            targets[key] = (targets[key][0], True)

    for entry in inv.entries:
        target(Path(entry.path), entry.loaded in LOADED_LABELS)
    ws_files = [p for p in iter_files(ws, skip)]
    for path in ws_files:
        target(path, str(path.resolve()) in ctx_keys)
    extras = []
    for raw in extra_scan:
        extras.append(Path(raw).expanduser().resolve())
    for path in extras:
        for file in iter_files(path, skip):
            target(file, str(file.resolve()) in ctx_keys)

    # Session stores the chosen CLI can resume. Not auto-loaded, so REVIEW.
    sessions = []
    if cli in ("claude", "generic") and memory.get("project_dir") is not None:
        project_dir = memory["project_dir"]
        memory_path = memory["directory"].resolve() if memory.get("directory") else None
        for file in iter_files(project_dir, skip):
            if memory_path is None or not (is_below(file, memory_path) or file.parent == memory_path):
                sessions.append(file)
    if cli in ("codex", "generic"):
        for name in ("history.jsonl",):
            candidate = homes.codex_home / name
            if candidate.is_file():
                sessions.append(candidate)
        sessions_dir = homes.codex_home / "sessions"
        if sessions_dir.is_dir():
            sessions.extend(iter_files(sessions_dir, frozenset()))
    for file in sessions:
        target(file, False)

    scanned = 0
    skipped_content = 0
    for key, (path, in_ctx) in targets.items():
        display = str(path)
        name_findings(col, display, path, in_ctx)
        if is_env_file(path):
            text = read_text_if_small(path)
            if text is not None:
                scan_env_file(col, display, text, in_ctx)
            continue
        text = read_text_if_small(path)
        if text is None:
            skipped_content += 1
            continue
        scanned += 1
        scan_content(col, display, text, in_ctx, path.suffix.lower() in CODE_EXT)

    git_status = "skipped: disabled"
    if use_git:
        pairs, git_status = git_history_names(ws)
        seen_paths = set()
        for commit, rel in pairs:
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            fake = Path(rel)
            name_findings(col, f"git:{commit}:{rel}", fake, False, git_commit=commit)

    # Presence facts (INFO).
    for entry in inv.entries:
        if entry.loaded == "not loaded":
            col.add("INFO", "present but not loaded by this CLI", entry.path, None,
                    entry.rule, None, False)
    if memory and not memory["enabled"] and memory["directory"] and memory["directory"].is_dir():
        col.add("INFO", "auto memory disabled", str(memory["directory"]), None,
                f"auto memory is off ({memory['reason']}); files are still readable by the agent's tools",
                None, False)
    if memory and memory.get("other_project_dirs"):
        col.add("INFO", "other project directories under the CLI home", str(homes.claude_dir / "projects"),
                None, f"{len(memory['other_project_dirs'])} other project directory name(s); not loaded here, "
                      "readable by the Read tool unless denied; names only, not scanned", None, False)
    for name in SHELL_HISTORY_NAMES:
        candidate = homes.home / name
        if candidate.is_file():
            col.add("INFO", "shell history present, not scanned", str(candidate), None,
                    "readable by the Bash tool; pass --extra-scan to scan it", None, False)
    if skipped_content:
        col.add("INFO", "content not scanned", str(ws), None,
                f"{skipped_content} binary, oversize or unreadable file(s) had names checked only", None, False)
    if git_status != "read" and use_git:
        col.add("INFO", "git history not read", str(ws), None, git_status, None, False)

    findings = [asdict(f) for f in col.findings]
    summary = {v: sum(1 for f in findings if f["verdict"] == v) for v in ("BLOCK", "REVIEW", "INFO")}
    overall = "BLOCK" if summary["BLOCK"] else ("REVIEW" if summary["REVIEW"] else "INFO")
    exit_code = 1 if summary["BLOCK"] else 0
    record = {
        "schema": SCHEMA,
        "timestamp_utc": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cli": cli,
        "cli_rule_source": RULE_SOURCES[cli],
        "workspace": str(ws),
        "project_root": str(root),
        "homes": {"home": str(homes.home), "claude_dir": str(homes.claude_dir),
                  "codex_home": str(homes.codex_home), "opencode_dir": str(homes.opencode_dir)},
        "auto_memory": {
            "enabled": bool(memory.get("enabled")) if memory else None,
            "reason": memory.get("reason") if memory else "not applicable to this CLI",
            "directory": str(memory["directory"]) if memory and memory.get("directory") else None,
            "project_key": memory.get("project_key") if memory else None,
        },
        "env_flags_set": {name: name in environ for name in ENV_FLAGS},
        "context_files": [asdict(e) for e in inv.entries],
        "not_found": sorted(set(inv.absent)),
        "scan": {
            "workspace_files": len(ws_files),
            "content_scanned": scanned,
            "content_skipped": skipped_content,
            "targets_total": len(targets),
            "extra_scan": [str(p) for p in extras],
            "session_files": len(sessions),
            "git_history": git_status,
        },
        "findings": findings,
        "summary": summary,
        "overall": overall,
        "exit_code": exit_code,
        "limits": LIMITS,
    }
    return record, findings


def render_report(record: dict) -> str:
    def cell(text) -> str:
        text = "" if text is None else str(text)
        return text.replace("|", "\\|").replace("\n", " ")

    def code(text) -> str:
        return "`" + cell(text).replace("`", "'") + "`"

    out = []
    out.append(f"# Pre-lock audit: {record['cli']}")
    out.append("")
    out.append(f"- Workspace: {code(record['workspace'])}")
    out.append(f"- Timestamp (UTC): {record['timestamp_utc']}")
    out.append(f"- Context-loading rule source: {record['cli_rule_source']}")
    out.append(f"- Overall: **{record['overall']}**. Exit code: {record['exit_code']}.")
    s = record["summary"]
    out.append(f"- Counts: BLOCK {s['BLOCK']}, REVIEW {s['REVIEW']}, INFO {s['INFO']}.")
    out.append("")
    out.append("Verdicts. **BLOCK**: held-out data or scores inside auto-loaded context. Do not lock until removed. "
               "**REVIEW**: scores, notes, held-out names or secret-like values the agent can read with its tools; "
               "a person decides and records the decision. **INFO**: presence facts that need no action under the rules.")
    out.append("")
    out.append("## Context files")
    out.append("")
    if record["context_files"]:
        out.append("| Path | Rule | Loaded | Bytes | SHA-256 |")
        out.append("|---|---|---|---|---|")
        for entry in record["context_files"]:
            via = f" (imported from {entry['imported_from']})" if entry.get("imported_from") else ""
            out.append(f"| {code(entry['path'])} | {cell(entry['rule'])}{cell(via)} | {cell(entry['loaded'])} | "
                       f"{entry['bytes']} | `{entry['sha256']}` |")
    else:
        out.append("None found.")
    out.append("")
    out.append("Checked and absent: " + (", ".join(code(p) for p in record["not_found"][:20]) or "none")
               + (" (list truncated)" if len(record["not_found"]) > 20 else "") + ".")
    out.append("")
    out.append("## Findings")
    for verdict in ("BLOCK", "REVIEW", "INFO"):
        out.append("")
        out.append(f"### {verdict}")
        out.append("")
        rows = [f for f in record["findings"] if f["verdict"] == verdict]
        if not rows:
            out.append("None.")
            continue
        out.append("| Location | Category | Detail | Excerpt |")
        out.append("|---|---|---|---|")
        for f in rows:
            loc = f"{f['path']}:{f['line']}" if f["line"] else f["path"]
            excerpt = code(f["excerpt"]) if f["excerpt"] is not None else ""
            out.append(f"| {code(loc)} | {cell(f['category'])} | {cell(f['detail'])} | {excerpt} |")
    out.append("")
    out.append("## Scan coverage")
    out.append("")
    sc = record["scan"]
    out.append(f"- Workspace files seen: {sc['workspace_files']}. Targets scanned for content: {sc['content_scanned']}. "
               f"Skipped as binary, oversize or unreadable: {sc['content_skipped']}.")
    out.append(f"- Session stores included: {sc['session_files']}. Extra paths: {len(sc['extra_scan'])}. "
               f"Git history: {sc['git_history']}.")
    out.append("")
    out.append("## Limits")
    out.append("")
    for item in record["limits"]:
        out.append(f"- {item}")
    out.append("")
    return "\n".join(out)


def write_outputs(out_dir: Path, record: dict) -> tuple:
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / "prelock_lock.json"
    report_path = out_dir / "prelock_report.md"
    lock_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(record), encoding="utf-8")
    return lock_path, report_path


def parse_args(argv: Optional[list]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-lock contamination audit for a Virtual Embryo Agent Team run.")
    parser.add_argument("--workspace", required=True, help="directory the agent will run in")
    parser.add_argument("--cli", required=True, choices=CLI_CHOICES, help="agent CLI that will run")
    parser.add_argument("--out", required=True, help="directory for prelock_lock.json and prelock_report.md")
    parser.add_argument("--home", help="home directory to use instead of the current user's (for synthetic runs and tests)")
    parser.add_argument("--memory-dir", help="auto memory directory to use instead of the derived one")
    parser.add_argument("--extra-scan", action="append", default=[],
                        help="additional file or directory the agent can read, for example a shell history file (repeatable)")
    parser.add_argument("--redact-excerpts", action="store_true", help="omit excerpts from the lock record and report")
    parser.add_argument("--no-git", action="store_true", help="skip git history")
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    if not ws.is_dir():
        print(f"prelock_audit: workspace is not a directory: {ws}", file=sys.stderr)
        return 2
    out_dir = Path(args.out).expanduser().resolve()
    skip = frozenset({str(out_dir)})
    if out_dir == ws or ws in out_dir.parents:
        print("prelock_audit: warning: output directory is inside the workspace; "
              "the agent could read its own lock record. Output directory excluded from the scan.", file=sys.stderr)
    record, _ = run_audit(
        ws, args.cli,
        home=args.home,
        memory_dir=Path(args.memory_dir).expanduser() if args.memory_dir else None,
        extra_scan=args.extra_scan,
        use_git=not args.no_git,
        redact=args.redact_excerpts,
        skip=skip,
    )
    lock_path, report_path = write_outputs(out_dir, record)
    s = record["summary"]
    print(f"prelock_audit: cli={args.cli} overall={record['overall']} exit={record['exit_code']}")
    print(f"  BLOCK {s['BLOCK']}  REVIEW {s['REVIEW']}  INFO {s['INFO']}")
    print(f"  lock record: {lock_path}")
    print(f"  report:      {report_path}")
    return record["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
