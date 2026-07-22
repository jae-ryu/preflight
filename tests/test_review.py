"""`preflight review <pr>` — the one-command entrypoint. gh + council mocked."""
import json

from preflight import api, cli, crew


def _install_council(monkeypatch, roaster, mammoth, mc):
    def fake(model, system, user, max_tokens, node=None):
        if system is crew.ROASTER_SYS:
            return (roaster, True)
        if system is crew.MAMMOTH_SYS:
            return (mammoth, True)
        if system is crew.MC_SYS:
            return (mc, True)
        raise AssertionError("unknown system prompt")
    monkeypatch.setattr(api, "council_call", fake)


DIFF = "diff --git a/f.py b/f.py\n@@ -1 +1 @@\n+x\n"
HIGH = {"sev": "high", "where": "f.py:1", "issue": "bug", "say": "roast"}


def _stub_gh(monkeypatch, captured):
    """Stub the gh seams: fetch returns a canned PR, upsert records the call."""
    def fetch(pr, repo=None):
        return DIFF, "abc123", ["f.py"], repo or "owner/repo"

    def upsert(repo, pr, body):
        captured["repo"] = repo
        captured["pr"] = pr
        captured["body"] = body
        return "posted"

    monkeypatch.setattr(cli, "_fetch_pr", fetch)
    monkeypatch.setattr(cli, "_upsert_comment", upsert)


def test_review_preview_does_not_post(monkeypatch, capsys):
    monkeypatch.setenv("MODULAR_API_KEY", "test")
    _install_council(
        monkeypatch,
        roaster={"summary": "bugs", "findings": [HIGH]},
        mammoth={"summary": "ok", "findings": []},
        mc={"score": 60, "verdict": "HOLD", "summary": "hold", "top_actions": ["fix"]},
    )
    captured = {}
    _stub_gh(monkeypatch, captured)
    rc = cli.main(["review", "92708", "--repo", "owner/repo", "--goal", "85"])
    out = capsys.readouterr().out
    assert rc == 1  # HOLD
    assert "captured" not in out
    assert captured == {}  # preview: nothing posted
    # The one comprehensive comment is printed, with the marker + score.
    assert "<!-- preflight-council -->" in out
    assert "HOLD" in out and "/100" in out


def test_review_post_upserts_one_comment(monkeypatch):
    monkeypatch.setenv("MODULAR_API_KEY", "test")
    _install_council(
        monkeypatch,
        roaster={"summary": "clean", "findings": []},
        mammoth={"summary": "clean", "findings": []},
        mc={"score": 100, "verdict": "GO", "summary": "ship", "top_actions": []},
    )
    captured = {}
    _stub_gh(monkeypatch, captured)
    rc = cli.main(["review", "5", "--repo", "owner/repo", "--post"])
    assert rc == 0  # GO
    assert captured["repo"] == "owner/repo"
    assert captured["pr"] == "5"
    assert "<!-- preflight-council -->" in captured["body"]


def test_review_no_key_is_infra(monkeypatch):
    monkeypatch.delenv("MODULAR_API_KEY", raising=False)
    rc = cli.main(["review", "5"])
    assert rc == 2


def test_review_writes_json_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("MODULAR_API_KEY", "test")
    _install_council(
        monkeypatch,
        roaster={"summary": "bugs", "findings": [HIGH]},
        mammoth={"summary": "ok", "findings": []},
        mc={"score": 60, "verdict": "HOLD", "summary": "x", "top_actions": []},
    )
    _stub_gh(monkeypatch, {})
    out = tmp_path / "run.json"
    cli.main(["review", "5", "--repo", "o/r", "--json", str(out)])
    data = json.loads(out.read_text())
    assert data["version"] == 2
    assert data["verdict"] == "HOLD"


def test_repo_slug_parsed_from_url():
    assert cli._repo_slug_from_url(
        "https://github.com/modularml/modular/pull/92708") == "modularml/modular"
    assert cli._repo_slug_from_url("not a url") is None
