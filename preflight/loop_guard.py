"""
loop_guard.py — the honest-loop stop rules (§05) as pure functions.

The self-improvement loop is: score → propose a change → re-score → keep or
revert. Left unguarded it drifts into three classic failure modes, and this
module is the set of decision functions that catch each. They DECIDE; they do
NOT run the loop — the caller (a skill, CI, a human) calls them and obeys.

Every function is pure: same inputs, same answer, no I/O. Decisions return a
{"stop"|"ok"|"allow": bool, "reason": str, ...} dict so a log can record WHY,
not just that it halted.

The four guards:

  1. ITERATION CAP — never coach→rerun a single PR forever. Cheap runaway guard.
  2. OVERFITTING — the self-reported (coached) score climbs while the frozen
     HOLDOUT stays flat. That gap means we are tuning to the one PR in front of
     us, not getting genuinely better. Uses the holdout the same way anchor.py
     freezes code: improvement must generalize.
  3. CYCLE — a proposed change reverts a change we already made (A→B then B→A).
     Left unchecked the loop oscillates forever between two states.
  4. GRADUATION — a failure-class tag only enters the charter when it recurs
     CONFIRMED-REAL (acted-on via feedback.py), never on raw recurrence. Noise
     that repeats is still noise; only signal that repeats earns a rule.
"""

# --- defaults (tunable by the caller; these are the report §05 starting points)
DEFAULT_MAX_ITERS = 3
DEFAULT_OVERFIT_GAP = 15  # coached-minus-holdout points that flags overfitting
DEFAULT_HOLDOUT_MIN_GAIN = 1  # holdout must move at least this to count as real
DEFAULT_GRADUATE_MIN_CONFIRMED = 3  # confirmed-real recurrences before charter


def iteration_cap_reached(iterations, cap=DEFAULT_MAX_ITERS):
    """Stop when coach→rerun count for a PR reaches the cap.

    `iterations` = coaching rounds already completed. Returns a stop decision;
    stop is True once iterations >= cap. A non-positive cap disables coaching
    entirely (stop from the start).
    """
    try:
        n = int(iterations)
    except (TypeError, ValueError):
        n = 0
    stop = n >= cap
    return {
        "stop": stop,
        "reason": (
            f"iteration cap reached ({n}/{cap})" if stop else f"under cap ({n}/{cap})"
        ),
        "iterations": n,
        "cap": cap,
    }


def is_overfitting(
    coached_score,
    holdout_score,
    baseline_holdout=None,
    gap_threshold=DEFAULT_OVERFIT_GAP,
    min_holdout_gain=DEFAULT_HOLDOUT_MIN_GAIN,
):
    """Overfitting detector: coached score rises but the holdout stays flat.

    - `coached_score`: current self-score on the PR being coached.
    - `holdout_score`: current mean score on the frozen holdout set.
    - `baseline_holdout` (optional): holdout mean BEFORE this change; when given,
      "flat" means it gained less than `min_holdout_gain`. When omitted we fall
      back to the raw coached-minus-holdout gap alone.

    Overfitting iff the coached↔holdout gap exceeds `gap_threshold` AND the
    holdout did not meaningfully gain. Returns a decision with the measured gap.
    """
    if coached_score is None or holdout_score is None:
        return {
            "overfit": False,
            "reason": "insufficient data (missing score)",
            "gap": None,
        }
    gap = coached_score - holdout_score
    holdout_gain = (
        None if baseline_holdout is None else holdout_score - baseline_holdout
    )
    flat = holdout_gain is None or holdout_gain < min_holdout_gain
    overfit = gap > gap_threshold and flat
    return {
        "overfit": overfit,
        "reason": (
            f"coached {coached_score} vs holdout {holdout_score} "
            f"(gap {gap} > {gap_threshold}) and holdout "
            f"{'flat' if flat else 'gained'}"
            if overfit
            else f"gap {gap} within tolerance or holdout gained"
        ),
        "gap": gap,
        "holdout_gain": holdout_gain,
        "gap_threshold": gap_threshold,
    }


def _change_id(change):
    """A change is {'target', 'before', 'after'}. Its id is (target, before, after)."""
    if not isinstance(change, dict):
        return None
    return (change.get("target"), change.get("before"), change.get("after"))


def is_cycle(change, history):
    """True-ish decision when `change` reverts any change already in `history`.

    A change A→B on a target cycles if history holds B→A on the same target
    (or the identical A→B, i.e. re-applying a no-op we already did). `history`
    is the list of previously-applied change dicts. Malformed entries are
    ignored, never fatal.
    """
    cid = _change_id(change)
    if cid is None:
        return {"cycle": False, "reason": "change is not a dict"}
    target, before, after = cid
    for prior in history or []:
        pid = _change_id(prior)
        if pid is None:
            continue
        p_target, p_before, p_after = pid
        if p_target != target:
            continue
        # exact repeat of an applied change, or a straight revert of one.
        if (p_before, p_after) == (before, after):
            return {
                "cycle": True,
                "reason": f"repeats an applied change on {target!r}",
                "target": target,
            }
        if (p_before, p_after) == (after, before):
            return {
                "cycle": True,
                "reason": f"reverts a prior change on {target!r} "
                f"({before!r}->{after!r} undoes {p_before!r}->{p_after!r})",
                "target": target,
            }
    return {"cycle": False, "reason": "no matching prior change"}


def can_graduate(
    confirmed_real,
    recurrence=None,
    min_confirmed=DEFAULT_GRADUATE_MIN_CONFIRMED,
):
    """Decide whether a failure-class tag may auto-graduate into the charter.

    Gate is on CONFIRMED-REAL recurrences (findings acted-on per feedback.py),
    NOT raw recurrence — a class that keeps getting DISMISSED is noise that
    repeats, and must never earn a charter rule. `recurrence` (raw sightings)
    is accepted for context/logging only; it does not lower the bar.

    Graduates iff confirmed_real >= min_confirmed.
    """
    try:
        confirmed = int(confirmed_real)
    except (TypeError, ValueError):
        confirmed = 0
    allow = confirmed >= min_confirmed
    return {
        "allow": allow,
        "reason": (
            f"{confirmed} confirmed-real >= {min_confirmed}"
            if allow
            else f"only {confirmed} confirmed-real (need {min_confirmed}); "
            f"raw recurrence {recurrence} does not count"
        ),
        "confirmed_real": confirmed,
        "recurrence": recurrence,
        "min_confirmed": min_confirmed,
    }


def should_stop(iterations, coached_score, holdout_score, **kw):
    """Convenience: fold the two run-time guards (cap, overfit) into one
    decision the loop checks before another coach round. Returns
    {"stop": bool, "reason": str}. Cycle + graduation are per-change /
    per-tag decisions the caller makes at their own decision points.
    """
    cap = iteration_cap_reached(iterations, kw.get("cap", DEFAULT_MAX_ITERS))
    if cap["stop"]:
        return {"stop": True, "reason": cap["reason"]}
    over = is_overfitting(
        coached_score,
        holdout_score,
        baseline_holdout=kw.get("baseline_holdout"),
        gap_threshold=kw.get("gap_threshold", DEFAULT_OVERFIT_GAP),
        min_holdout_gain=kw.get("min_holdout_gain", DEFAULT_HOLDOUT_MIN_GAIN),
    )
    if over["overfit"]:
        return {"stop": True, "reason": over["reason"]}
    return {"stop": False, "reason": "guards clear — another round is allowed"}
