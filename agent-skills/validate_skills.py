#!/usr/bin/env python3
"""Check the agent skills in this folder.

    python validate_skills.py [ROOT]

For each folder under ROOT that holds a SKILL.md, the script checks that the
file opens with YAML frontmatter, that `name` is kebab-case and equals the
folder name, that `description` is present and at most 1024 characters, and
that the file is at most 120 lines. It also checks that every relative Markdown
link in each SKILL.md and in ROOT/README.md resolves to an existing file.
Standard library only. Exit code 0 when every check passes, 1 otherwise.
"""

import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.*)$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
MAX_DESCRIPTION = 1024
MAX_LINES = 120
# Characters that cannot start a plain YAML scalar.
YAML_INDICATORS = "[]{}!&*|>'\"%@`#,?"


def parse_frontmatter(text):
    """Return (fields, error). Supports single-line `key: value` pairs only."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, "frontmatter must open with --- on the first line"
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None, "frontmatter has no closing ---"
    fields = {}
    for number, line in enumerate(lines[1:end], start=2):
        if not line.strip():
            continue
        match = FIELD_RE.match(line)
        if not match:
            return None, f"line {number} is not a single-line key: value pair"
        key, value = match.group(1), match.group(2).strip()
        if key in fields:
            return None, f"line {number} repeats the key {key}"
        if value and value[0] in YAML_INDICATORS:
            return None, f"line {number}: value starts with {value[0]!r}, which YAML reads as syntax"
        if ": " in value:
            return None, f"line {number}: value contains ': ', which YAML reads as a mapping; rephrase"
        fields[key] = value
    return fields, None


def check_skill(skill_dir):
    """Return a list of error strings for one skill folder."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{skill_dir}: no SKILL.md"]
    text = skill_md.read_text(encoding="utf-8")
    errors = []
    fields, error = parse_frontmatter(text)
    if error:
        return [f"{skill_md}: {error}"]
    name = fields.get("name", "")
    if not name:
        errors.append(f"{skill_md}: name is missing")
    elif name != skill_dir.name:
        errors.append(f"{skill_md}: name {name!r} does not match folder {skill_dir.name!r}")
    elif not NAME_RE.match(name):
        errors.append(f"{skill_md}: name {name!r} is not kebab-case")
    if name == "synced" or name.startswith("anthropic-skills"):
        errors.append(f"{skill_md}: name {name!r} is reserved by Claude Code")
    description = fields.get("description", "")
    if not description:
        errors.append(f"{skill_md}: description is missing")
    elif len(description) > MAX_DESCRIPTION:
        errors.append(f"{skill_md}: description is {len(description)} characters, limit {MAX_DESCRIPTION}")
    line_count = len(text.splitlines())
    if line_count > MAX_LINES:
        errors.append(f"{skill_md}: {line_count} lines, limit {MAX_LINES}")
    return errors


def check_links(md_file):
    """Return an error for each relative link in md_file that does not resolve."""
    errors = []
    base = md_file.parent
    for match in LINK_RE.finditer(md_file.read_text(encoding="utf-8")):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = target.split("#", 1)[0]
        if path and not (base / path).resolve().exists():
            errors.append(f"{md_file}: broken relative link {target!r}")
    return errors


def validate_tree(root):
    """Return every error found under root. Empty list means the tree is valid."""
    root = Path(root)
    skill_dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").exists())
    errors = []
    if not skill_dirs:
        errors.append(f"{root}: no skill folders with a SKILL.md")
    for skill_dir in skill_dirs:
        errors.extend(check_skill(skill_dir))
        errors.extend(check_links(skill_dir / "SKILL.md"))
    readme = root / "README.md"
    if readme.is_file():
        errors.extend(check_links(readme))
    return errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path(__file__).resolve().parent
    errors = validate_tree(root)
    for error in errors:
        print(error)
    if errors:
        print(f"{len(errors)} problem(s) found under {root}")
        return 1
    print(f"ok: all skills under {root} pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
