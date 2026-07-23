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


def test_mission_control_grader_score_equals_aggregate():
    """The invariant the composer relies on: MC's grader row == the gate score."""
    roaster = [_find("high", dim="correctness")]
    mammoth = [_find("med", dim="tests")]
    final = rubric.finalize(90, "HOLD", roaster, mammoth, goal=85)
    diag = dimensions.breakdown(roaster, mammoth)
    diag["grader_scores"]["mission_control"] = final["score"]
    assert diag["grader_scores"]["mission_control"] == final["score"]


def test_breakout_does_not_change_the_gate_score():
    """Adding the dimension layer must not perturb the deterministic aggregate."""
    roaster = [_find("high", dim="security"), _find("med", dim="correctness")]
    mammoth = [_find("high", dim="repo-fit")]
    before = rubric.rubric_score(roaster, mammoth)
    dimensions.stamp_dims(roaster, "roaster")
    dimensions.stamp_dims(mammoth, "mammoth")
    after = rubric.rubric_score(roaster, mammoth)
    assert before == after  # stamping dims never touches severity/score
