"""Honest-loop stop rules: iteration cap, overfitting, cycle, graduation."""
from preflight import loop_guard as lg


# ---- iteration cap -----------------------------------------------------------


def test_iteration_cap_not_reached():
    d = lg.iteration_cap_reached(1, cap=3)
    assert d["stop"] is False


def test_iteration_cap_reached_at_boundary():
    assert lg.iteration_cap_reached(3, cap=3)["stop"] is True
    assert lg.iteration_cap_reached(4, cap=3)["stop"] is True


def test_iteration_cap_zero_disables_coaching():
    assert lg.iteration_cap_reached(0, cap=0)["stop"] is True


def test_iteration_cap_bad_input_treated_as_zero():
    assert lg.iteration_cap_reached(None, cap=3)["stop"] is False
    assert lg.iteration_cap_reached("x", cap=1)["stop"] is False


# ---- overfitting detector ----------------------------------------------------


def test_overfitting_flagged_when_gap_big_and_holdout_flat():
    # coached rockets to 95, holdout stuck at 70, no prior gain => overfit.
    d = lg.is_overfitting(95, 70, baseline_holdout=70, gap_threshold=15)
    assert d["overfit"] is True
    assert d["gap"] == 25


def test_overfitting_not_flagged_when_holdout_also_gained():
    # holdout climbed from 60 to 78 alongside the coached score => real gain.
    d = lg.is_overfitting(95, 78, baseline_holdout=60, gap_threshold=15)
    assert d["overfit"] is False


def test_overfitting_not_flagged_when_gap_within_tolerance():
    d = lg.is_overfitting(80, 74, baseline_holdout=74, gap_threshold=15)
    assert d["overfit"] is False


def test_overfitting_without_baseline_uses_raw_gap():
    assert lg.is_overfitting(95, 70, gap_threshold=15)["overfit"] is True
    assert lg.is_overfitting(80, 74, gap_threshold=15)["overfit"] is False


def test_overfitting_missing_scores_is_safe():
    d = lg.is_overfitting(None, 70)
    assert d["overfit"] is False
    assert d["gap"] is None


# ---- cycle detection ---------------------------------------------------------


def test_cycle_detects_revert():
    history = [{"target": "rubric.NIT_CAP", "before": 10, "after": 8}]
    change = {"target": "rubric.NIT_CAP", "before": 8, "after": 10}  # undo
    d = lg.is_cycle(change, history)
    assert d["cycle"] is True


def test_cycle_detects_exact_repeat():
    history = [{"target": "x", "before": 1, "after": 2}]
    d = lg.is_cycle({"target": "x", "before": 1, "after": 2}, history)
    assert d["cycle"] is True


def test_cycle_no_match_different_target():
    history = [{"target": "x", "before": 1, "after": 2}]
    d = lg.is_cycle({"target": "y", "before": 2, "after": 1}, history)
    assert d["cycle"] is False


def test_cycle_empty_history():
    assert lg.is_cycle({"target": "x", "before": 1, "after": 2}, [])["cycle"] is False


def test_cycle_tolerates_malformed():
    assert lg.is_cycle("nope", [])["cycle"] is False
    d = lg.is_cycle({"target": "x", "before": 1, "after": 2}, ["junk", None])
    assert d["cycle"] is False


def test_cycle_no_false_positive_on_targetless_changes():
    # council-caught round 2: two changes missing keys both id as (None,None,None)
    # and must NOT be treated as a repeat/revert of each other.
    change = {"before": 1, "after": 2}  # no target
    history = [{"note": "also targetless"}]
    assert lg.is_cycle(change, history)["cycle"] is False


# ---- graduation gate ---------------------------------------------------------


def test_graduate_allowed_on_confirmed_real():
    d = lg.can_graduate(confirmed_real=3, recurrence=5, min_confirmed=3)
    assert d["allow"] is True


def test_graduate_blocked_when_recurrence_high_but_confirmed_low():
    # class recurs 20 times but only 1 was acted-on => noise that repeats.
    d = lg.can_graduate(confirmed_real=1, recurrence=20, min_confirmed=3)
    assert d["allow"] is False
    assert "does not count" in d["reason"]


def test_graduate_bad_input_treated_as_zero():
    assert lg.can_graduate(None, min_confirmed=1)["allow"] is False


# ---- should_stop convenience -------------------------------------------------


def test_should_stop_on_cap():
    d = lg.should_stop(iterations=3, coached_score=80, holdout_score=79, cap=3)
    assert d["stop"] is True
    assert "cap" in d["reason"]


def test_should_stop_on_overfit():
    d = lg.should_stop(
        iterations=1, coached_score=95, holdout_score=70,
        baseline_holdout=70, cap=5,
    )
    assert d["stop"] is True


def test_should_stop_clear():
    d = lg.should_stop(
        iterations=1, coached_score=82, holdout_score=80,
        baseline_holdout=78, cap=5,
    )
    assert d["stop"] is False
