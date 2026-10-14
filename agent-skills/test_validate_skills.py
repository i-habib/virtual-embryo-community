"""Tests for validate_skills.py. Run from this folder with: python -m pytest -q"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import validate_skills as vs  # noqa: E402

GOOD_BODY = "# Title\n\nSome instructions.\n"


def write_skill(root, name, frontmatter, body=GOOD_BODY):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(frontmatter + body, encoding="utf-8")
    return folder


def good_frontmatter(name, description="Does a thing. Use when a thing needs doing."):
    return f"---\nname: {name}\ndescription: {description}\n---\n"


def test_valid_skill_passes(tmp_path):
    folder = write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo"))
    assert vs.check_skill(folder) == []
    assert vs.validate_tree(tmp_path) == []


def test_name_must_match_folder(tmp_path):
    folder = write_skill(tmp_path, "vec-demo", good_frontmatter("vec-other"))
    errors = vs.check_skill(folder)
    assert any("does not match folder" in e for e in errors)


def test_name_must_be_kebab_case(tmp_path):
    folder = write_skill(tmp_path, "Vec_Demo", good_frontmatter("Vec_Demo"))
    errors = vs.check_skill(folder)
    assert any("not kebab-case" in e for e in errors)


def test_reserved_name_is_reported(tmp_path):
    folder = write_skill(tmp_path, "synced", good_frontmatter("synced"))
    assert any("reserved" in e for e in vs.check_skill(folder))


def test_missing_frontmatter_is_reported(tmp_path):
    folder = write_skill(tmp_path, "vec-demo", "no frontmatter here\n")
    assert vs.check_skill(folder)


def test_frontmatter_must_start_on_first_line(tmp_path):
    folder = write_skill(tmp_path, "vec-demo", "\n" + good_frontmatter("vec-demo"))
    assert any("first line" in e for e in vs.check_skill(folder))


def test_missing_description_is_reported(tmp_path):
    folder = write_skill(tmp_path, "vec-demo", "---\nname: vec-demo\n---\n")
    assert any("description is missing" in e for e in vs.check_skill(folder))


def test_description_over_1024_characters_is_reported(tmp_path):
    folder = write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo", "x" * 1025))
    assert any("limit 1024" in e for e in vs.check_skill(folder))


def test_description_of_1024_characters_passes(tmp_path):
    folder = write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo", "x" * 1024))
    assert vs.check_skill(folder) == []


def test_colon_space_in_value_is_reported(tmp_path):
    folder = write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo", "Note: this breaks YAML"))
    assert any("': '" in e for e in vs.check_skill(folder))


def test_long_skill_is_reported(tmp_path):
    body = "line\n" * 130
    folder = write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo"), body=body)
    assert any("limit 120" in e for e in vs.check_skill(folder))


def test_broken_relative_link_is_reported(tmp_path):
    body = "See [missing](../no-such-folder/README.md).\n"
    write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo"), body=body)
    errors = vs.validate_tree(tmp_path)
    assert any("broken relative link" in e for e in errors)


def test_resolving_relative_link_passes(tmp_path):
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "README.md").write_text("x", encoding="utf-8")
    body = "See [other](../other/README.md#section).\n"
    write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo"), body=body)
    assert vs.validate_tree(tmp_path) == []


def test_external_and_anchor_links_are_ignored(tmp_path):
    body = "[web](https://virtualembryo.ai/challenge/rules) [mail](mailto:a@b.c) [top](#heading)\n"
    write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo"), body=body)
    assert vs.validate_tree(tmp_path) == []


def test_readme_links_are_checked(tmp_path):
    write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo"))
    (tmp_path / "README.md").write_text("[gone](vec-gone/SKILL.md)\n", encoding="utf-8")
    assert any("vec-gone" in e for e in vs.validate_tree(tmp_path))


def test_empty_root_is_reported(tmp_path):
    assert vs.validate_tree(tmp_path)


def test_main_exit_codes(tmp_path):
    write_skill(tmp_path, "vec-demo", good_frontmatter("vec-demo"))
    assert vs.main([str(tmp_path)]) == 0
    write_skill(tmp_path, "vec-bad", good_frontmatter("vec-other"))
    assert vs.main([str(tmp_path)]) == 1


def test_real_skills_folder_is_valid():
    assert vs.validate_tree(HERE) == []
