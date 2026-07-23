"""End-to-end contract assembly + exit codes. API fully mocked at council_call."""
import json

import pytest

from preflight import api, cli, crew, dimensions


def _install_council(monkeypatch, roaster, mammoth, mc, roaster_ok=True,
                     mammoth_ok=True, mc_ok=True):
    """Route council_call to canned payloads keyed by which system prompt is used."""
    def fake(model, system, user, max_tokens, node=None):
        if system is crew.ROASTER_SYS:
            return (roaster, roaster_ok)
        if system is crew.MAMMOTH_SYS:
            return (mammoth, mammoth_ok)
        if system is crew.MC_SYS:
            return (mc, mc_ok)
        raise AssertionError("unknown system prompt")
    monkeypatch.setattr(api, "council_call", fake)


HIGH = {"sev": "high", "where": "f.py:1", "issue": "bug", "say": "roast"}
MED = {"sev": "med", "where": "f.py:2", "issue": "meh", "say": "note"}
DIFF = "diff --git a/f.py b/f.py\n@@ -1 +1 @@\n+x\n"


def test_contract_shape_and_hold(monkeypatch):
    _install_council(
        monkeypatch,
        roaster={"summary": "bugs", "findings": [HIGH]},
        mammoth={"summary": "design", "findings": [MED]},
        mc={"score": 80, "verdict": "GO", "summary": "looks close", "top_actions": ["fix bug"]},
    )
    result, infra_ok = cli.build_result(DIFF, goal=85)
    # Frozen contract keys (v3 — adds the per-grader/per-dimension breakout).
    assert set(result) == {"version", "goal", "score", "verdict", "blockers",
                           "nits", "rubric_score", "model_score", "grader_scores",
                           "dimension_scores", "summary", "top_actions",
                           "reviewers", "meta", "trace", "totals"}
    assert result["version"] == 3
    # Breakout shape: three graders, each lane's dimensions present.
    assert set(result["grader_scores"]) == {"roaster", "mammoth", "mission_control"}
    assert set(result["dimension_scores"]["roaster"]) == set(dimensions.LANES["roaster"])
    assert set(result["dimension_scores"]["mammoth"]) == set(dimensions.LANES["mammoth"])
    assert set(result["reviewers"]) == {"roaster", "mammoth"}
    for rev in result["reviewers"].values():
        assert set(rev) == {"summary", "findings", "parse_ok"}
    assert set(result["meta"]) == {"models", "diff_bytes", "truncated",
                                   "chunks", "skipped_files", "changed_files"}
    # totals present with the expected shape (trace is empty when council_call is mocked).
    assert set(result["totals"]) == {"wall_ms", "tokens"}
    assert set(result["totals"]["tokens"]) == {"prompt", "completion", "reasoning"}
    assert result["meta"]["models"] == {
        "reviewers": "moonshotai/Kimi-K2.6", "overseer": "google/gemma-4-31B-it"}
    assert result["meta"]["chunks"] == 1  # small diff -> single pass
    assert result["meta"]["skipped_files"] == []
    # blocker/nit counts populated; findings carry deterministic tiers.
    assert result["blockers"] == 1  # roaster HIGH
    assert result["nits"] == 1      # mammoth MED
    assert result["reviewers"]["roaster"]["findings"][0]["tier"] == "blocker"
    assert result["reviewers"]["mammoth"]["findings"][0]["tier"] == "nit"
    # A blocker stands -> deterministic HOLD even though model said GO.
    assert result["verdict"] == "HOLD"
    assert infra_ok is True


def test_go_path(monkeypatch):
    _install_council(
        monkeypatch,
        roaster={"summary": "clean", "findings": []},
        mammoth={"summary": "clean", "findings": [MED]},
        mc={"score": 95, "verdict": "GO", "summary": "ship it", "top_actions": []},
    )
    result, infra_ok = cli.build_result(DIFF, goal=85)
    assert result["verdict"] == "GO"
    assert result["score"] == 95  # 100 - 5 (med)


def test_both_reviewers_unparseable_is_infra_failure(monkeypatch):
    _install_council(
        monkeypatch,
        roaster=None, roaster_ok=False,
        mammoth=None, mammoth_ok=False,
        mc={"score": 0, "verdict": "HOLD", "summary": "x", "top_actions": []},
    )
    result, infra_ok = cli.build_result(DIFF, goal=85)
    assert infra_ok is False
    assert result["reviewers"]["roaster"]["parse_ok"] is False
    assert result["reviewers"]["mammoth"]["parse_ok"] is False


def _big_diff(n_files, body_lines=200):
    """Build a diff large enough to force the map-reduce path (> 24k chars)."""
    out = []
    for i in range(n_files):
        hunk = "@@ -1,3 +1,3 @@\n" + "\n".join(f"+line {j} of file {i}" for j in range(body_lines))
        out.append(f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n{hunk}\n")
    return "".join(out)


def test_chunked_path_maps_and_reduces(monkeypatch):
    # Compression is a separate light-model seam; stub it so no network is hit.
    monkeypatch.setattr(crew, "compress_summaries",
                        lambda summaries: (summaries[0] if summaries else ""))
    _install_council(
        monkeypatch,
        roaster={"summary": "bugs", "findings": [HIGH, MED]},
        mammoth={"summary": "design", "findings": [MED]},
        mc={"score": 80, "verdict": "GO", "summary": "chunked", "top_actions": []},
    )
    big = _big_diff(8)
    assert len(big) > 24000
    result, infra_ok = cli.build_result(big, goal=85)
    assert infra_ok is True
    # Map-reduce actually chunked the diff.
    assert result["meta"]["chunks"] > 1
    # Findings deduped across chunks (same `where` in every chunk collapses to one each).
    r_findings = result["reviewers"]["roaster"]["findings"]
    assert len(r_findings) == 2  # HIGH + MED, not 2*chunks
    assert result["blockers"] == 1  # one roaster HIGH survives dedupe
    # Blocker stands -> HOLD.
    assert result["verdict"] == "HOLD"


def test_chunked_caps_findings_per_reviewer(monkeypatch):
    monkeypatch.setattr(crew, "compress_summaries", lambda s: s[0] if s else "")
    # Each chunk yields distinct wheres so caps (3 gating + 5 nits) actually bite.
    many_high = [{"sev": "high", "where": f"g{i}.py:1", "issue": "b", "say": "s"} for i in range(6)]
    many_nits = [{"sev": "med", "where": f"n{i}.py:1", "issue": "b", "say": "s"} for i in range(8)]

    def fake(model, system, user, max_tokens, node=None):
        if system is crew.MC_SYS:
            return ({"score": 50, "verdict": "HOLD", "summary": "x", "top_actions": []}, True)
        # Return findings whose `where` varies per chunk so nothing dedupes away.
        tag = str(abs(hash(user)) % 1000)
        f = [{**x, "where": x["where"] + tag} for x in (many_high + many_nits)]
        return ({"summary": "s", "findings": f}, True)

    monkeypatch.setattr(api, "council_call", fake)
    big = _big_diff(8)
    result, _ = cli.build_result(big, goal=85)
    for name in ("roaster", "mammoth"):
        findings = result["reviewers"][name]["findings"]
        gating = [x for x in findings if x["sev"] == "high"]
        nits = [x for x in findings if x["sev"] in ("med", "low")]
        assert len(gating) <= 3
        assert len(nits) <= 5


def test_main_exit_go(monkeypatch, tmp_path):
    monkeypatch.setenv("MODULAR_API_KEY", "test")
    _install_council(
        monkeypatch,
        roaster={"summary": "clean", "findings": []},
        mammoth={"summary": "clean", "findings": []},
        mc={"score": 100, "verdict": "GO", "summary": "go", "top_actions": []},
    )
    diff_file = tmp_path / "d.diff"
    diff_file.write_text(DIFF)
    out = tmp_path / "out.json"
    rc = cli.main(["run", str(diff_file), "--goal", "85", "--json", str(out)])
    assert rc == 0
    saved = json.loads(out.read_text())
    assert saved["verdict"] == "GO"


def test_main_exit_hold(monkeypatch, tmp_path):
    monkeypatch.setenv("MODULAR_API_KEY", "test")
    _install_council(
        monkeypatch,
        roaster={"summary": "bugs", "findings": [HIGH]},
        mammoth={"summary": "ok", "findings": []},
        mc={"score": 85, "verdict": "GO", "summary": "hmm", "top_actions": ["fix"]},
    )
    diff_file = tmp_path / "d.diff"
    diff_file.write_text(DIFF)
    rc = cli.main(["run", str(diff_file), "--goal", "80"])
    assert rc == 1


def test_main_exit_infra_when_both_unparseable(monkeypatch, tmp_path):
    monkeypatch.setenv("MODULAR_API_KEY", "test")
    _install_council(
        monkeypatch,
        roaster=None, roaster_ok=False,
        mammoth=None, mammoth_ok=False,
        mc={"score": 0, "verdict": "HOLD", "summary": "x", "top_actions": []},
    )
    diff_file = tmp_path / "d.diff"
    diff_file.write_text(DIFF)
    rc = cli.main(["run", str(diff_file), "--goal", "80"])
    assert rc == 2


def test_main_no_key_is_infra(monkeypatch, tmp_path):
    monkeypatch.delenv("MODULAR_API_KEY", raising=False)
    diff_file = tmp_path / "d.diff"
    diff_file.write_text(DIFF)
    rc = cli.main(["run", str(diff_file)])
    assert rc == 2


def test_main_api_down_is_infra(monkeypatch, tmp_path):
    monkeypatch.setenv("MODULAR_API_KEY", "test")

    def boom(*a, **k):
        raise api.APIError("connection refused")

    monkeypatch.setattr(api, "council_call", boom)
    diff_file = tmp_path / "d.diff"
    diff_file.write_text(DIFF)
    rc = cli.main(["run", str(diff_file)])
    assert rc == 2
