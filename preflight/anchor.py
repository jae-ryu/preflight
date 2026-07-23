"""
anchor.py — rubric-drift measurement via a frozen anchor set (§06).

When you change the rubric, the score of every PR moves — but the CODE under
review did not. So a raw score trend across a rubric bump conflates two things:
the reviewers getting better (Δreal) and the ruler changing length (Δrubric).

The fix is an ANCHOR SET: a frozen list of past run result files whose diffs
never change. Re-score that identical set under two rubric versions and the mean
score delta on it is, by construction, PURE Δrubric — code held constant. Then
any observed change on live PRs can be netted:

    Δreal = Δscore − Δrubric

This module does the dual-scoring. It does NOT decide policy (that's loop_guard)
and it never calls the network — it re-scores stored findings with a scorer
callable, defaulting to the current rubric.

A rubric "version" here is just a scorer: a function
(roaster_findings, mammoth_findings) -> int in [0, 100]. rubric.rubric_score is
the v1 scorer. To measure a proposed v2, pass its scorer as `scorer_b`.
"""

import json
import os

from . import rubric


def load_anchor_set(manifest, base_dir=None):
    """Load the anchor run results named in `manifest` (a list of file paths).

    `manifest` is the holdout manifest from config (config.holdout): a list of
    paths to frozen run JSON files. Relative paths resolve against `base_dir`
    (default: repo root). Returns a list of {path, run} dicts; a missing or
    unreadable file is skipped with its path recorded under 'errors' — callers
    that need strictness can inspect the (runs, errors) via load_anchor_set_x.
    """
    runs, _ = load_anchor_set_x(manifest, base_dir=base_dir)
    return runs


def load_anchor_set_x(manifest, base_dir=None):
    """Like load_anchor_set but returns (runs, errors) — errors is a list of
    paths that could not be loaded, so a stale manifest is visible not silent."""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runs, errors = [], []
    for path in manifest or []:
        # A non-string manifest entry (os.path.join TypeError) or a file that
        # is not valid UTF-8 (UnicodeDecodeError) must not crash the loader —
        # record it as a bad entry, same as a missing/corrupt file.
        try:
            full = path if os.path.isabs(path) else os.path.join(base_dir, path)
            with open(full) as f:
                run = json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, UnicodeDecodeError):
            errors.append(path)
            continue
        if isinstance(run, dict):
            runs.append({"path": path, "run": run})
        else:
            errors.append(path)
    return runs, errors


def extract_findings(run):
    """(roaster_findings, mammoth_findings) from a run result dict.

    Non-dict findings are dropped (malformed LLM output must not crash a
    re-score). A run missing reviewers yields two empty lists.
    """
    reviewers = (run or {}).get("reviewers") or {}

    def _f(key):
        body = reviewers.get(key)
        # The reviewer body itself may be a non-dict (a list, str, …) from
        # malformed output; .get on it would raise, so bail to empty.
        if not isinstance(body, dict):
            return []
        raw = body.get("findings")
        # `findings` may be a non-list (int/bool/str); only iterate a real list.
        if not isinstance(raw, list):
            return []
        return [f for f in raw if isinstance(f, dict)]

    return _f("roaster"), _f("mammoth")


def score_run(run, scorer=None):
    """Re-score one run under `scorer` (default: current rubric.rubric_score)."""
    scorer = scorer or rubric.rubric_score
    r, m = extract_findings(run)
    return scorer(r, m)


def _mean(values):
    return round(sum(values) / len(values), 4) if values else None


def dual_score(anchor_runs, scorer_a=None, scorer_b=None):
    """Re-score the anchor set under two scorers and compute Δrubric.

    `anchor_runs` is the list returned by load_anchor_set (each {path, run}),
    or a bare list of run dicts. `scorer_a` is the baseline rubric (default
    current rubric.rubric_score); `scorer_b` is the candidate. Returns:

        {
          "n": <anchors scored>,
          "per_run": [{"path", "score_a", "score_b", "delta"}...],
          "mean_a", "mean_b",
          "delta_rubric": mean_b - mean_a,   # None if empty
        }

    delta_rubric is the exact offset to net out of any live score delta.
    """
    scorer_a = scorer_a or rubric.rubric_score
    scorer_b = scorer_b or rubric.rubric_score
    per_run, a_scores, b_scores = [], [], []
    for item in anchor_runs or []:
        if isinstance(item, dict) and "run" in item:
            path, run = item.get("path"), item.get("run")
        else:
            path, run = None, item
        sa = score_run(run, scorer_a)
        sb = score_run(run, scorer_b)
        a_scores.append(sa)
        b_scores.append(sb)
        per_run.append({"path": path, "score_a": sa, "score_b": sb, "delta": sb - sa})
    mean_a, mean_b = _mean(a_scores), _mean(b_scores)
    delta = round(mean_b - mean_a, 4) if per_run else None
    return {
        "n": len(per_run),
        "per_run": per_run,
        "mean_a": mean_a,
        "mean_b": mean_b,
        "delta_rubric": delta,
    }


def delta_real(delta_score, delta_rubric):
    """Δreal = Δscore − Δrubric: the change attributable to the reviewers, not
    the ruler. `delta_rubric` None (empty anchor set) means we cannot net it
    out, so Δreal is unknown — return None rather than a misleading number."""
    if delta_rubric is None or delta_score is None:
        return None
    return round(delta_score - delta_rubric, 4)
