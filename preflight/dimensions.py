"""Per-grader scoring dimensions — the robustness breakout.

The single aggregate score answers "ship or not" but hides *why*. This module
adds a second lens: every finding is attributed to a DIMENSION within its
grader's lane, and each dimension carries its own 0-100 sub-score. Roll the
dimensions up per grader, and the reader can see exactly which axis a PR is
weak on (e.g. Roaster clean on security but bleeding on failure-path).

Contract:
  - Each grader owns a FIXED, ordered set of dimensions (its lane). A clean
    dimension scores 100 and pulls the grader's mean UP — silence on an axis
    is a signal, not a gap.
  - A finding's dimension comes from its own ``dim`` field when the reviewer
    set a valid one; otherwise it is derived from the finding's ``tag`` via
    TAG_DIM; otherwise it falls to the lane's primary (first) dimension.
  - dim score = 100 - deductions from that dim's findings, floored at 0.
  - grader score = round(mean of the grader's dimension scores).

The aggregate/gate score (zero-blocker GO/HOLD) stays in rubric.py and is
unchanged — this layer is additive diagnostics, reported alongside it.
"""

# Ordered lane vocabularies. Order is the display order in the report.
LANES = {
    "roaster": ["correctness", "failure-path", "security", "resilience"],
    "mammoth": ["repo-fit", "tests", "docs", "maintainability"],
}

# Fallback: derive a dimension from a finding's failure-class tag when the
# reviewer did not emit a valid ``dim``. Keys are tag ids from tags.py.
TAG_DIM = {
    # roaster lane
    "logic-error": "correctness",
    "input-validation": "correctness",
    "naming-mismatch": "correctness",
    "wire-format": "correctness",
    "error-path-fidelity": "failure-path",
    "crash-blind-observability": "failure-path",
    "best-effort-side-effect": "failure-path",
    "wrong-exception-type": "failure-path",
    "exception-state-timing": "failure-path",
    "info-leak": "security",
    "input-validation-security": "security",
    "transport-safety": "resilience",
    "resource-leak": "resilience",
    "concurrency": "resilience",
    # mammoth lane
    "build-artifact": "repo-fit",
    "duplication": "repo-fit",
    "dead-code": "repo-fit",
    "missing-tests": "tests",
    "unverified-claim": "tests",
}

# Per-dimension deductions. Sharper than the aggregate rubric: a dimension is
# a narrow axis, so one blocker on it should visibly tank that sub-score while
# leaving the grader's other (clean) dimensions at 100.
DEDUCT = {"high": 30, "med": 10, "low": 4}


def _sev(f):
    return (f.get("sev") or "").lower()


def resolve_dim(finding, grader):
    """Return the lane dimension a finding belongs to (never raises)."""
    lane = LANES.get(grader, [])
    if not lane:
        return None
    dim = (finding.get("dim") or "").strip().lower()
    if dim in lane:
        return dim
    mapped = TAG_DIM.get((finding.get("tag") or "").strip().lower())
    if mapped in lane:
        return mapped
    return lane[0]


def stamp_dims(findings, grader):
    """Stamp each finding with its resolved lane dimension. Mutates, returns list."""
    for f in findings:
        if isinstance(f, dict):
            f["dim"] = resolve_dim(f, grader)
    return findings


def _dim_score(findings):
    score = 100
    for f in findings:
        score -= DEDUCT.get(_sev(f), 0)
    return max(0, score)


def grader_breakdown(findings, grader):
    """Return (dim_scores: {dim: 0-100}, grader_score: 0-100) for one lane.

    Findings must already be dim-stamped (via stamp_dims); any not stamped are
    resolved on the fly so this is safe to call standalone.
    """
    lane = LANES.get(grader, [])
    buckets = {d: [] for d in lane}
    for f in findings:
        d = f.get("dim") if f.get("dim") in lane else resolve_dim(f, grader)
        if d in buckets:
            buckets[d].append(f)
    dim_scores = {d: _dim_score(buckets[d]) for d in lane}
    grader_score = round(sum(dim_scores.values()) / len(lane)) if lane else 0
    return dim_scores, grader_score


def breakdown(roaster_findings, mammoth_findings):
    """Full diagnostic breakout across both graders.

    Returns:
      {
        "dimension_scores": {"roaster": {dim: score}, "mammoth": {dim: score}},
        "grader_scores":    {"roaster": int, "mammoth": int},
      }
    Mission Control's grader score is the finalized aggregate and is added by
    the caller (it is the gate number, computed in rubric.finalize).
    """
    r_dims, r_score = grader_breakdown(roaster_findings, "roaster")
    m_dims, m_score = grader_breakdown(mammoth_findings, "mammoth")
    return {
        "dimension_scores": {"roaster": r_dims, "mammoth": m_dims},
        "grader_scores": {"roaster": r_score, "mammoth": m_score},
    }
