import os
import sys

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "comment")),
)
import composer  # noqa: E402

from preflight import cli, crew

DIFF = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a = 1\n+a = 2\n"


def _run(monkeypatch, roaster_ok):
    crashed = {"summary": "(could not parse)", "findings": [], "parse_ok": False}
    clean = {"summary": "lgtm", "findings": [], "parse_ok": True}
    monkeypatch.setattr(
        crew, "run_reviewers",
        lambda *a, **k: (clean if roaster_ok else crashed, clean),
    )
    monkeypatch.setattr(
        crew, "run_overseer",
        lambda *a, **k: ({"score": 100, "verdict": "GO", "summary": "ship"}, True),
    )
    result, _ = cli.build_result(DIFF, 85)
    return result


def test_crashed_reviewer_scores_not_approve(monkeypatch):
    result = _run(monkeypatch, roaster_ok=False)
    assert result["verdict"] == "HOLD"
    assert result["grader_scores"]["roaster"] is None
    body = composer.compose(result)
    assert "unscored (review did not parse)" in body
    assert "→ **HOLD**" in body


def test_approving_reviewers_still_go(monkeypatch):
    result = _run(monkeypatch, roaster_ok=True)
    assert result["verdict"] == "GO"
    assert result["grader_scores"]["roaster"] == 100
    assert "🟢 **GO**" in composer.compose(result)
