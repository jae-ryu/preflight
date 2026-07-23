"""End-to-end scoring reconciliation — the rubric + dimension logic together.

The whole 71->33 confusion came from misreading how the score is produced, so
these tests PIN the exact math. If any of them break, the score's meaning
changed — that must be a deliberate, reviewed decision, never a silent drift.

Two layers under test:
  1. rubric.py  — the aggregate gate score (deterministic, blocker/nit) and the
     +/-5 model clamp + zero-blocker GO/HOLD gate.
  2. dimensions.py — the additive per-grader / per-dimension breakout.

And the invariant that ties them: Mission Control's grader score IS the
finalized aggregate.
"""

from preflight import dimensions, rubric


def _find(sev, dim=None, tag=None):
    f = {"sev": sev, "issue": "x", "where": "f.py:1"}
    if dim:
        f["dim"] = dim
    if tag:
        f["tag"] = tag
    return f


# ---------------------------------------------------------------------------
# The real 71 -> 33 reconciliation (verified against runs/pr92708-final2 & -v3).
# ---------------------------------------------------------------------------
# 71 run: 2 Roaster blockers, 0 Mammoth blockers, nits at the -10 cap, MC +5.
# 33 run: 3 Roaster blockers, 2 Mammoth blockers, nits at the -10 cap, MC -5.
# The -38 delta = +1 Roaster blocker (-12) + 2 Mammoth blockers (-16)
#                 + MC swing +5 -> -5 (-10).


def _nits_to_cap():
    # Four med nits = -12 raw, capped to -10. Guarantees the cap is hit.
    return [_find("med") for _ in range(4)]


def test_reconcile_71_run():
    roaster = [_find("high"), _find("high")] + _nits_to_cap()
    mammoth = []
    rub = rubric.rubric_score(roaster, mammoth)
    assert rub == 100 - 2 * 12 - 10  # 66
    # Overseer nudged +5 (model said 71, within band).
    final = rubric.finalize(71, "HOLD", roaster, mammoth, goal=85)
    assert final["rubric_score"] == 66
    assert final["score"] == 71  # 66 + 5 clamp band
    assert final["blockers"] == 2
    assert final["verdict"] == "HOLD"  # blockers present -> HOLD regardless


def test_reconcile_33_run():
    roaster = [_find("high"), _find("high"), _find("high")] + _nits_to_cap()
    mammoth = [_find("high"), _find("high")]
    rub = rubric.rubric_score(roaster, mammoth)
    assert rub == 100 - 3 * 12 - 2 * 8 - 10  # 38
    # Overseer nudged -5 (model said 33, within band).
    final = rubric.finalize(33, "HOLD", roaster, mammoth, goal=85)
    assert final["rubric_score"] == 38
    assert final["score"] == 33  # 38 - 5 clamp band
    assert final["blockers"] == 5


def test_the_minus_38_is_fully_accounted():
    """The drop is exactly +1 roaster blocker, +2 mammoth blockers, MC +5->-5."""
    r71 = [_find("high"), _find("high")] + _nits_to_cap()
    r33 = [_find("high"), _find("high"), _find("high")] + _nits_to_cap()
    m33 = [_find("high"), _find("high")]
    s71 = rubric.finalize(71, "HOLD", r71, [], goal=85)["score"]
    s33 = rubric.finalize(33, "HOLD", r33, m33, goal=85)["score"]
    assert s71 - s33 == 38
    # component breakdown
    extra_roaster = 1 * rubric.DEDUCT_BLOCKER_CORRECTNESS  # 12
    extra_mammoth = 2 * rubric.DEDUCT_BLOCKER_DESIGN  # 16
    mc_swing = 2 * rubric.CLAMP_BAND  # 10 (+5 -> -5)
    assert extra_roaster + extra_mammoth + mc_swing == 38


# ---------------------------------------------------------------------------
# The clamp is a HARD +/-5 band around the deterministic rubric.
# ---------------------------------------------------------------------------
def test_model_cannot_inflate_beyond_band():
    roaster = [_find("high")]  # rubric = 88
    final = rubric.finalize(100, "GO", roaster, [], goal=50)
    assert final["rubric_score"] == 88
    assert final["score"] == 93  # capped at 88 + 5, not 100


def test_model_cannot_deflate_beyond_band():
    final = rubric.finalize(0, "HOLD", [], [], goal=50)
    assert final["rubric_score"] == 100
    assert final["score"] == 95  # floored at 100 - 5, not 0


# ---------------------------------------------------------------------------
# Gate invariant: ANY blocker forces HOLD even at a passing score.
# ---------------------------------------------------------------------------
def test_any_blocker_forces_hold_even_above_goal():
    roaster = [_find("high")]  # score ~93, well above a goal of 50
    final = rubric.finalize(95, "GO", roaster, [], goal=50)
    assert final["blockers"] == 1
    assert final["verdict"] == "HOLD"


def test_go_only_with_zero_blockers_and_at_goal():
    final = rubric.finalize(90, "GO", [], [_find("low")], goal=85)
    assert final["blockers"] == 0
    assert final["verdict"] == "GO"


# ---------------------------------------------------------------------------
# Dimension breakout rolls up coherently and stays independent of the gate.
# ---------------------------------------------------------------------------
def test_dimension_breakout_isolates_weak_axis():
    # Two failure-path blockers; correctness/security/resilience untouched.
    roaster = [_find("high", dim="failure-path"), _find("high", dim="failure-path")]
    dims, grader = dimensions.grader_breakdown(roaster, "roaster")
    assert dims["failure-path"] == 100 - 2 * 30  # 40
    assert dims["correctness"] == 100
    assert grader == round((40 + 100 + 100 + 100) / 4)  # 85


def test_mission_control_grader_score_equals_aggregate(monkeypatch):
    """The invariant the composer relies on: MC's grader row == the gate score.

    Verified against the REAL assembly in cli.build_result (not a self-assign):
    whatever build_result puts in grader_scores['mission_control'] must equal
    the top-level result['score'].
    """
    from preflight import api, cli, crew

    def fake(model, system, user, max_tokens, node=None):
        if system is crew.MC_SYS:
            return (
                {"score": 90, "verdict": "GO", "summary": "x", "top_actions": []},
                True,
            )
        if system is crew.ROASTER_SYS:
            return (
                {"summary": "b", "findings": [_find("high", dim="correctness")]},
                True,
            )
        return ({"summary": "d", "findings": [_find("med", dim="tests")]}, True)

    monkeypatch.setattr(api, "council_call", fake)
    result, _ = cli.build_result("diff --git a/f b/f\n@@ -1 +1 @@\n+x\n", goal=85)
    assert result["grader_scores"]["mission_control"] == result["score"]


def test_grader_breakdown_survives_non_dict_findings():
    """Malformed LLM output (a bare string in findings) must not crash scoring."""
    findings = [_find("high", dim="correctness"), "garbage", None]
    dims, grader = dimensions.grader_breakdown(findings, "roaster")
    assert dims["correctness"] == 70  # the one real finding still counted
    assert 0 <= grader <= 100


def test_resolve_dim_never_raises_on_non_string(monkeypatch):
    """R-fix: a non-string dim/tag (int, list) must not crash resolve_dim."""
    assert dimensions.resolve_dim({"dim": 42}, "roaster") == "correctness"
    assert dimensions.resolve_dim({"tag": ["x"]}, "roaster") == "correctness"
    assert dimensions.resolve_dim({"dim": None, "tag": None}, "mammoth") == "repo-fit"


def test_unknown_severity_does_not_inflate_dimension():
    """R-fix: an unknown/missing severity must deduct (not silently score 0)."""
    findings = [{"dim": "correctness", "sev": "typo-not-a-sev"}]
    dims, _ = dimensions.grader_breakdown(findings, "roaster")
    assert dims["correctness"] == 100 - dimensions.DEDUCT["med"]  # not 100


def test_mammoth_has_design_dimension():
    """R3: design is now a distinct Mammoth lane dimension."""
    assert "design" in dimensions.LANES["mammoth"]
    assert dimensions.resolve_dim({"tag": "wrong-abstraction"}, "mammoth") == "design"


def test_rubric_version_stamped_on_finalize():
    """Every finalized score records the rubric_version that produced it."""
    final = rubric.finalize(90, "GO", [], [], goal=85)
    assert final["rubric_version"] == rubric.RUBRIC_VERSION


def test_overseer_gets_loc_for_size_gate(monkeypatch):
    """R2: the changed-line count is fed into Mission Control's prompt."""
    from preflight import api, crew

    seen = {}

    def fake(model, system, user, max_tokens, node=None):
        if node == "mission-control":
            seen["user"] = user
        return ({"score": 90, "verdict": "GO", "summary": "x", "top_actions": []}, True)

    monkeypatch.setattr(api, "council_call", fake)
    crew.run_overseer(85, {"findings": []}, {"findings": []}, loc=1234)
    assert "1234" in seen["user"]


def test_breakout_does_not_change_the_gate_score():
    """Adding the dimension layer must not perturb the deterministic aggregate."""
    roaster = [_find("high", dim="security"), _find("med", dim="correctness")]
    mammoth = [_find("high", dim="repo-fit")]
    before = rubric.rubric_score(roaster, mammoth)
    dimensions.stamp_dims(roaster, "roaster")
    dimensions.stamp_dims(mammoth, "mammoth")
    after = rubric.rubric_score(roaster, mammoth)
    assert before == after  # stamping dims never touches severity/score
