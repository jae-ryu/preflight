"""Tests for the per-grader / per-dimension scoring breakout."""

from preflight import dimensions as D


def _f(sev, dim=None, tag=None):
    f = {"sev": sev}
    if dim:
        f["dim"] = dim
    if tag:
        f["tag"] = tag
    return f


def test_resolve_dim_prefers_explicit_valid_dim():
    assert D.resolve_dim(_f("high", dim="security"), "roaster") == "security"


def test_resolve_dim_falls_back_to_tag_then_primary():
    # No dim, but a tag that maps into the lane.
    assert D.resolve_dim(_f("high", tag="resource-leak"), "roaster") == "resilience"
    # Neither dim nor tag -> the lane's primary dimension.
    assert D.resolve_dim(_f("high"), "roaster") == "correctness"
    # A dim not in this grader's lane is ignored, falls back to primary.
    assert D.resolve_dim(_f("high", dim="repo-fit"), "roaster") == "correctness"


def test_clean_dimension_scores_100():
    dims, score = D.grader_breakdown([], "roaster")
    assert dims == {d: 100 for d in D.LANES["roaster"]}
    assert score == 100


def test_one_blocker_tanks_only_its_dimension():
    findings = [_f("high", dim="failure-path")]
    dims, score = D.grader_breakdown(findings, "roaster")
    assert dims["failure-path"] == 70  # 100 - 30
    assert dims["correctness"] == 100  # untouched
    assert score == round((70 + 100 + 100 + 100) / 4)  # 92


def test_dimension_floor_at_zero():
    findings = [_f("high", dim="correctness")] * 5  # 5 * -30 = -150
    dims, _ = D.grader_breakdown(findings, "roaster")
    assert dims["correctness"] == 0


def test_breakdown_shape():
    b = D.breakdown([_f("high", dim="security")], [_f("med", dim="tests")])
    assert set(b["dimension_scores"]) == {"roaster", "mammoth"}
    assert set(b["dimension_scores"]["roaster"]) == set(D.LANES["roaster"])
    assert set(b["grader_scores"]) == {"roaster", "mammoth"}
    assert b["dimension_scores"]["roaster"]["security"] == 70
    assert b["dimension_scores"]["mammoth"]["tests"] == 90  # 100 - 10 (med)


def test_tag_dim_targets_are_all_valid_lane_dims():
    all_dims = set(D.LANES["roaster"]) | set(D.LANES["mammoth"])
    for tag, dim in D.TAG_DIM.items():
        assert dim in all_dims, f"{tag} maps to unknown dim {dim}"
