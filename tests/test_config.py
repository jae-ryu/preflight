"""Baked-in defaults + .council.yml overlay + precedence."""
from preflight import config


def test_defaults_when_no_file(tmp_path):
    cfg = config.load(council_yml=str(tmp_path / "nope.yml"))
    assert cfg.goal == config.DEFAULT_GOAL == 85
    assert cfg.paths == []
    assert cfg.holdout == []


def test_holdout_block_list(tmp_path):
    y = tmp_path / ".council.yml"
    y.write_text("goal: 90\nholdout:\n  - runs/anchor-1.json\n  - runs/anchor-2.json\n")
    cfg = config.load(council_yml=str(y))
    assert cfg.holdout == ["runs/anchor-1.json", "runs/anchor-2.json"]
    assert cfg.goal == 90


def test_holdout_inline_list(tmp_path):
    y = tmp_path / ".council.yml"
    y.write_text('holdout: ["runs/a.json", "runs/b.json"]\n')
    cfg = config.load(council_yml=str(y))
    assert cfg.holdout == ["runs/a.json", "runs/b.json"]


def test_paths_and_holdout_blocks_coexist(tmp_path):
    y = tmp_path / ".council.yml"
    y.write_text("paths:\n  - src/\nholdout:\n  - runs/a.json\n")
    cfg = config.load(council_yml=str(y))
    assert cfg.paths == ["src/"]
    assert cfg.holdout == ["runs/a.json"]


def test_council_yml_overrides_defaults(tmp_path):
    y = tmp_path / ".council.yml"
    y.write_text("goal: 90\npaths:\n  - src/\n  - '*.py'\n")
    cfg = config.load(council_yml=str(y))
    assert cfg.goal == 90
    assert cfg.paths == ["src/", "*.py"]


def test_flag_beats_council_yml(tmp_path):
    y = tmp_path / ".council.yml"
    y.write_text("goal: 90\n")
    cfg = config.load(council_yml=str(y), goal=70)
    assert cfg.goal == 70  # explicit flag wins


def test_none_overrides_are_ignored(tmp_path):
    y = tmp_path / ".council.yml"
    y.write_text("goal: 92\n")
    cfg = config.load(council_yml=str(y), goal=None, cap=None)
    assert cfg.goal == 92  # unset flags don't clobber the file


def test_inline_paths_list(tmp_path):
    y = tmp_path / ".council.yml"
    y.write_text('paths: ["a/", "b/"]\n')
    cfg = config.load(council_yml=str(y))
    assert cfg.paths == ["a/", "b/"]


DIFF = (
    "diff --git a/src/x.py b/src/x.py\n@@ -1 +1 @@\n+keep\n"
    "diff --git a/docs/y.md b/docs/y.md\n@@ -1 +1 @@\n+drop\n"
)


def test_filter_diff_keeps_matching_paths():
    out = config.filter_diff(DIFF, ["src/"])
    assert "src/x.py" in out
    assert "docs/y.md" not in out


def test_filter_diff_empty_patterns_passthrough():
    assert config.filter_diff(DIFF, []) == DIFF


def test_council_yml_strips_inline_comments(tmp_path):
    y = tmp_path / ".council.yml"
    y.write_text("paths:\n  - src/   # only sources\n  - '*.py'  # python\n")
    cfg = config.load(council_yml=str(y))
    assert cfg.paths == ["src/", "*.py"]  # comments stripped, not part of path


def test_filter_diff_glob_matches_nested():
    diff = (
        "diff --git a/deep/nested/x.py b/deep/nested/x.py\n@@ -1 +1 @@\n+keep\n"
        "diff --git a/deep/y.txt b/deep/y.txt\n@@ -1 +1 @@\n+drop\n"
    )
    out = config.filter_diff(diff, ["*.py"])
    assert "deep/nested/x.py" in out   # *.py now matches at any depth
    assert "y.txt" not in out
