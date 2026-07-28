"""Anchor-set dual-scoring: Δrubric measurement, load, extract, Δreal."""
import json

from preflight import anchor, rubric


def _run(roaster=None, mammoth=None):
    return {"reviewers": {
        "roaster": {"findings": roaster or []},
        "mammoth": {"findings": mammoth or []},
    }}


def test_extract_findings_drops_non_dict():
    run = _run(roaster=[{"sev": "high"}, "junk", None], mammoth=[{"sev": "med"}])
    r, m = anchor.extract_findings(run)
    assert r == [{"sev": "high"}]
    assert m == [{"sev": "med"}]


def test_extract_findings_missing_reviewers():
    assert anchor.extract_findings({}) == ([], [])
    assert anchor.extract_findings(None) == ([], [])


def test_extract_findings_non_list_findings_does_not_crash():
    # council-caught: findings as int/bool/str must not explode the comprehension.
    run = {"reviewers": {"roaster": {"findings": 5}, "mammoth": {"findings": "x"}}}
    assert anchor.extract_findings(run) == ([], [])


def test_extract_findings_non_dict_reviewer_body_does_not_crash():
    # council-caught round 2: a list-shaped reviewer body would AttributeError on .get.
    run = {"reviewers": {"roaster": ["oops"], "mammoth": "nope"}}
    assert anchor.extract_findings(run) == ([], [])


def test_score_run_default_rubric():
    # one roaster high (-12) => 88 under v1 rubric.
    run = _run(roaster=[{"sev": "high"}])
    assert anchor.score_run(run) == 88
    assert anchor.score_run(run) == rubric.rubric_score([{"sev": "high"}], [])


def test_dual_score_delta_rubric_zero_when_same_scorer():
    runs = [_run(roaster=[{"sev": "high"}]), _run(mammoth=[{"sev": "med"}])]
    out = anchor.dual_score(runs)
    assert out["n"] == 2
    assert out["delta_rubric"] == 0.0
    assert out["mean_a"] == out["mean_b"]


def test_dual_score_measures_offset_between_two_rubrics():
    # scorer_b is harsher: subtract an extra flat 10 from the v1 score.
    def harsher(r, m):
        return max(0, rubric.rubric_score(r, m) - 10)

    runs = [_run(roaster=[{"sev": "high"}]),  # v1: 88
            _run(mammoth=[{"sev": "high"}])]  # v1: 92
    out = anchor.dual_score(runs, scorer_a=rubric.rubric_score, scorer_b=harsher)
    assert out["mean_a"] == 90.0  # (88 + 92) / 2
    assert out["mean_b"] == 80.0
    assert out["delta_rubric"] == -10.0  # pure ruler change, code held constant
    assert out["per_run"][0]["delta"] == -10


def test_dual_score_empty_anchor_set():
    out = anchor.dual_score([])
    assert out["n"] == 0
    assert out["delta_rubric"] is None
    assert out["mean_a"] is None


def test_dual_score_accepts_wrapped_and_bare_runs():
    wrapped = [{"path": "x.json", "run": _run(roaster=[{"sev": "high"}])}]
    out = anchor.dual_score(wrapped)
    assert out["per_run"][0]["path"] == "x.json"
    assert out["per_run"][0]["score_a"] == 88


def test_delta_real_nets_out_rubric():
    # observed +7 on live PRs, of which +2 was the rubric change => +5 real.
    assert anchor.delta_real(7, 2) == 5
    # unknown rubric offset (empty anchor set) => cannot net => None.
    assert anchor.delta_real(7, None) is None
    assert anchor.delta_real(None, 2) is None


# ---- load_anchor_set from a manifest -----------------------------------------


def test_load_anchor_set_reads_files(tmp_path):
    r1 = tmp_path / "r1.json"
    r1.write_text(json.dumps(_run(roaster=[{"sev": "high"}])))
    runs = anchor.load_anchor_set([str(r1)], base_dir=str(tmp_path))
    assert len(runs) == 1
    assert runs[0]["path"] == str(r1)
    assert anchor.score_run(runs[0]["run"]) == 88


def test_load_anchor_set_relative_paths(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_run()))
    runs = anchor.load_anchor_set(["a.json"], base_dir=str(tmp_path))
    assert len(runs) == 1


def test_load_anchor_set_records_errors_for_stale_manifest(tmp_path):
    runs, errors = anchor.load_anchor_set_x(
        ["missing.json"], base_dir=str(tmp_path)
    )
    assert runs == []
    assert errors == ["missing.json"]


def test_load_anchor_set_skips_non_dict_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]")  # valid json, not a run dict
    runs, errors = anchor.load_anchor_set_x([str(bad)], base_dir=str(tmp_path))
    assert runs == []
    assert errors == [str(bad)]


def test_load_anchor_set_tolerates_non_string_entry(tmp_path):
    # council-caught: a non-string manifest entry must be recorded, not crash.
    runs, errors = anchor.load_anchor_set_x([123, None], base_dir=str(tmp_path))
    assert runs == []
    assert errors == [123, None]


def test_load_anchor_set_empty_manifest():
    assert anchor.load_anchor_set([]) == []
    assert anchor.load_anchor_set(None) == []


def test_dual_score_over_loaded_anchor_end_to_end(tmp_path):
    for i, run in enumerate([_run(roaster=[{"sev": "high"}]), _run()]):
        (tmp_path / f"r{i}.json").write_text(json.dumps(run))
    runs = anchor.load_anchor_set(["r0.json", "r1.json"], base_dir=str(tmp_path))
    out = anchor.dual_score(runs)
    assert out["n"] == 2
    assert out["mean_a"] == 94.0  # (88 + 100) / 2
