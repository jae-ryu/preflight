"""
Deterministic scoring + triage. The model proposes; the rubric disposes.

Contract v2 — gentler math, blocker/nit triage.

TIERING (deterministic, in code — reviewers do NOT choose it):
  - blocker = any high-severity finding, from either reviewer.
  - nit     = any medium/low-severity finding.

SCORING (start at 100, deduct):
  - blocker CORRECTNESS (ROASTER high):  -12 each
  - blocker DESIGN/TESTS (MAMMOTH high):  -8 each
  - nit medium:                           -3 each
  - nit low:                              -1 each
  - TOTAL nit deduction is capped at     -10
Floor 0, cap 100.

The overseer may nudge the score for holistic judgment, but code CLAMPS the model
score to rubric +/-5. Verdict is GO only if final score >= goal AND there are ZERO
blockers (any high-severity finding, either reviewer) — that gate is enforced here
in code regardless of what the model said.
"""

CLAMP_BAND = 5

# Blocker (high-severity) deductions.
DEDUCT_BLOCKER_CORRECTNESS = 12   # ROASTER high
DEDUCT_BLOCKER_DESIGN = 8         # MAMMOTH high

# Nit (med/low) deductions, with a combined cap.
DEDUCT_NIT_MED = 3
DEDUCT_NIT_LOW = 1
NIT_CAP = 10


def _sev(f):
    return (f.get("sev") or "").lower()


def is_blocker(finding):
    """A finding is a blocker iff it is high severity."""
    return _sev(finding) == "high"


def tier_of(finding):
    """Deterministic tier for a finding: 'blocker' (high) or 'nit' (med/low)."""
    return "blocker" if is_blocker(finding) else "nit"


def apply_tiers(findings):
    """Stamp each finding with its deterministic 'tier'. Mutates in place, returns list."""
    for f in findings:
        if isinstance(f, dict):
            f["tier"] = tier_of(f)
    return findings


def count_tiers(roaster_findings, mammoth_findings):
    """Return (blockers, nits) counts across both reviewers."""
    blockers = sum(1 for f in roaster_findings if is_blocker(f)) \
        + sum(1 for f in mammoth_findings if is_blocker(f))
    nits = sum(1 for f in roaster_findings if not is_blocker(f)) \
        + sum(1 for f in mammoth_findings if not is_blocker(f))
    return blockers, nits


def _blocker_deduction(findings, high_cost):
    return sum(high_cost for f in findings if _sev(f) == "high")


def _nit_deduction(findings):
    total = 0
    for f in findings:
        sev = _sev(f)
        if sev == "med":
            total += DEDUCT_NIT_MED
        elif sev == "low":
            total += DEDUCT_NIT_LOW
    return total


def rubric_score(roaster_findings, mammoth_findings):
    """Recompute the deterministic score from findings alone (v2 math)."""
    score = 100
    score -= _blocker_deduction(roaster_findings, DEDUCT_BLOCKER_CORRECTNESS)
    score -= _blocker_deduction(mammoth_findings, DEDUCT_BLOCKER_DESIGN)

    nits = _nit_deduction(roaster_findings) + _nit_deduction(mammoth_findings)
    score -= min(nits, NIT_CAP)

    return max(0, min(100, score))


def has_blockers(roaster_findings, mammoth_findings):
    """True if any blocker (high-severity finding) stands, either reviewer."""
    return any(is_blocker(f) for f in roaster_findings) \
        or any(is_blocker(f) for f in mammoth_findings)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def finalize(model_score, model_verdict, roaster_findings, mammoth_findings, goal):
    """Resolve the final (score, verdict).

    Returns a dict: {score, verdict, rubric_score, model_score, blockers, nits}.
    """
    rub = rubric_score(roaster_findings, mammoth_findings)

    try:
        ms = int(model_score)
    except (TypeError, ValueError):
        ms = rub

    # Clamp the model's score to the deterministic rubric +/-5, then to [0, 100].
    final_score = _clamp(ms, rub - CLAMP_BAND, rub + CLAMP_BAND)
    final_score = _clamp(final_score, 0, 100)

    blockers, nits = count_tiers(roaster_findings, mammoth_findings)

    # Deterministic verdict. GO iff score >= goal AND zero blockers.
    verdict = "GO" if (final_score >= goal and blockers == 0) else "HOLD"

    return {
        "score": final_score,
        "verdict": verdict,
        "rubric_score": rub,
        "model_score": ms,
        "blockers": blockers,
        "nits": nits,
    }
