"""Deterministic scoring v2: gentler math, nit cap, blocker gating, tiering, +/-5 clamp."""
from preflight import rubric


def _f(sev):
    return {"sev": sev, "where": "x", "issue": "y", "say": "z"}


# ---------- tiering (deterministic, code decides) ----------

def test_tier_of_is_deterministic():
    assert rubric.tier_of(_f("high")) == "blocker"
    assert rubric.tier_of(_f("med")) == "nit"
    assert rubric.tier_of(_f("low")) == "nit"


def test_apply_tiers_stamps_findings():
    fs = [_f("high"), _f("med"), _f("low")]
    rubric.apply_tiers(fs)
    assert [f["tier"] for f in fs] == ["blocker", "nit", "nit"]


def test_count_tiers():
    r = [_f("high"), _f("med")]
    m = [_f("high"), _f("low"), _f("low")]
    blockers, nits = rubric.count_tiers(r, m)
    assert blockers == 2
    assert nits == 3


# ---------- rubric math (v2) ----------

def test_rubric_math_basic():
    # roaster: 1 high(-12) + 1 med(-3); mammoth: 1 high(-8) + 1 low(-1) => 100-24 = 76
    r = [_f("high"), _f("med")]
    m = [_f("high"), _f("low")]
    assert rubric.rubric_score(r, m) == 76


def test_nit_deduction_capped_at_10():
    # 5 med nits = -15 raw, but capped at -10 => 90. No blockers.
    r = [_f("med")] * 5
    assert rubric.rubric_score(r, []) == 90


def test_nit_cap_across_both_reviewers():
    # roaster 3 med (-9) + mammoth 3 med (-9) = -18 raw -> capped -10 => 90
    r = [_f("med")] * 3
    m = [_f("med")] * 3
    assert rubric.rubric_score(r, m) == 90


def test_nit_cap_does_not_touch_blockers():
    # 1 correctness blocker (-12) + capped nits (-10) => 78
    r = [_f("high")] + [_f("med")] * 5
    assert rubric.rubric_score(r, []) == 78


def test_low_nits_below_cap_not_capped():
    # 4 low nits = -4, under the -10 cap => 96
    assert rubric.rubric_score([_f("low")] * 4, []) == 96


def test_rubric_floor_zero():
    r = [_f("high")] * 20  # -240 correctness
    assert rubric.rubric_score(r, []) == 0


def test_rubric_clean_diff_is_100():
    assert rubric.rubric_score([], []) == 100


def test_blocker_costs_differ_by_reviewer():
    # correctness high -12, design high -8
    assert rubric.rubric_score([_f("high")], []) == 88
    assert rubric.rubric_score([], [_f("high")]) == 92


# ---------- blocker detection ----------

def test_has_blockers_either_reviewer():
    assert rubric.has_blockers([_f("high")], []) is True
    assert rubric.has_blockers([], [_f("high")]) is True
    assert rubric.has_blockers([_f("med")], [_f("low")]) is False


# ---------- clamp ----------

def test_clamp_model_score_above_band():
    # rubric = 76; model claims 95 -> clamp to 81
    r = [_f("high"), _f("med")]
    m = [_f("high"), _f("low")]
    out = rubric.finalize(95, "GO", r, m, goal=85)
    assert out["rubric_score"] == 76
    assert out["score"] == 81  # 76 + 5


def test_clamp_model_score_below_band():
    r = [_f("med")]  # rubric = 97
    out = rubric.finalize(10, "HOLD", r, [], goal=85)
    assert out["score"] == 92  # 97 - 5


def test_within_band_kept():
    r = [_f("med")]  # rubric 97
    out = rubric.finalize(96, "GO", r, [], goal=85)
    assert out["score"] == 96


# ---------- verdict gating ----------

def test_deterministic_hold_override_on_blocker():
    # Model says GO with a high score, but a blocker stands => HOLD.
    r = [_f("high")]  # rubric 88, blocker present
    out = rubric.finalize(88, "GO", r, [], goal=80)
    assert out["blockers"] == 1
    assert out["verdict"] == "HOLD"


def test_hold_override_on_design_blocker():
    # A MAMMOTH high (design) is also a blocker -> HOLD even above goal.
    m = [_f("high")]  # rubric 92
    out = rubric.finalize(92, "GO", [], m, goal=80)
    assert out["verdict"] == "HOLD"


def test_go_when_above_goal_and_no_blocker():
    m = [_f("low")]  # rubric 99
    out = rubric.finalize(99, "GO", [], m, goal=85)
    assert out["verdict"] == "GO"
    assert out["score"] == 99
    assert out["blockers"] == 0
    assert out["nits"] == 1


def test_hold_when_below_goal():
    r = [_f("med"), _f("med")]  # rubric 94, no blockers
    out = rubric.finalize(94, "GO", r, [], goal=95)
    assert out["verdict"] == "HOLD"


def test_bad_model_score_defaults_to_rubric():
    r = [_f("med")]  # rubric 97
    out = rubric.finalize(None, "GO", r, [], goal=85)
    assert out["score"] == 97
    assert out["verdict"] == "GO"
