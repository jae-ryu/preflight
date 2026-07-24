"""
feedback.py — ground-truth outcomes joined to the run ledger.

The council's scores are self-reported: they say a finding matters, but only
the *world* knows if it did. This module ingests real outcomes and joins them
to the per-run ledger `stats.py` already writes, so the loop can measure itself
against reality instead of against its own rubric.

Two kinds of outcome arrive as a small JSON/JSONL that CI or a human writes
(see FEEDBACK FORMAT below):

  - per-FINDING outcome — was a finding *acted-on*, *dismissed*, or *unknown*?
  - per-PR outcome — did CI pass? did the PR merge?

The north-star quality metric is the **SIGNAL RATIO**:

    signal_ratio = findings acted-on / findings with a determined outcome

It is deliberately RUBRIC-INVARIANT: it never reads a score. A rubric change
(§06 Δrubric) cannot move it — only the reviewers actually getting more useful
moves it. `unknown` outcomes are excluded from the denominator (no verdict yet),
and tracked separately so a low answer-rate is visible rather than hidden.

FEEDBACK FORMAT (one JSON object per JSONL line, or a top-level JSON array):

  finding outcome:
    {"kind": "finding", "repo": "o/r", "pr": "123",
     "where": "api.py:40", "outcome": "acted-on",
     "grader": "roaster", "dim": "correctness", "tag": "logic-error"}

    `outcome` is one of acted-on | dismissed | unknown. `grader`/`dim`/`tag`
    are OPTIONAL — when omitted they are back-filled from the run ledger by
    matching (repo, pr, where) against the recorded findings_detail, so a
    human can write the minimal `{where, outcome}` and still get full
    per-dimension / per-grader / per-tag rollups.

  pr outcome:
    {"kind": "pr", "repo": "o/r", "pr": "123",
     "ci_passed": true, "merged": true}

Nothing here calls the network. All functions are pure over the records passed
in (or the on-disk ledgers), and tolerant of malformed rows — a corrupt line
never kills a metric.
"""

import json
import os

from . import stats

ACTED_ON = "acted-on"
DISMISSED = "dismissed"
UNKNOWN = "unknown"
_DETERMINED = (ACTED_ON, DISMISSED)

DEFAULT_FEEDBACK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "runs",
    "feedback.jsonl",
)


def _resolve(path):
    """Feedback path: explicit arg > $PREFLIGHT_FEEDBACK > DEFAULT_FEEDBACK."""
    return path or os.environ.get("PREFLIGHT_FEEDBACK") or DEFAULT_FEEDBACK


def load(path=None):
    """Load feedback records from a JSONL file or a JSON array. Tolerant.

    Missing file -> []. A corrupt JSONL line is skipped, not fatal. A top-level
    JSON array is also accepted (whole-file parse) for hand-authored feedback.
    """
    path = _resolve(path)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        # unreadable feedback file (perms, or the path is a directory) degrades
        # to no records rather than crashing — same spirit as missing-file
        return []
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            arr = json.loads(text)
            return [r for r in arr if isinstance(r, dict)]
        except json.JSONDecodeError:
            pass  # fall through to line-by-line
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _key(repo, pr, where):
    return (str(repo or ""), str(pr or ""), str(where or ""))


def _ledger_index(ledger_rows):
    """Map (repo, pr, where) -> {grader, dim, tag} from ledger findings_detail.

    The stats ledger records one row per character per run; reviewer rows carry
    `findings_detail`, a list of {dim, tag, sev, tier, where, kind}. We index by
    location so finding-feedback can be enriched with the grader/dim/tag the
    council assigned, even when the human only wrote {where, outcome}.
    """
    index = {}
    for row in ledger_rows or []:
        if not isinstance(row, dict):
            continue
        grader = row.get("character")
        detail = row.get("findings_detail")
        if not isinstance(detail, list):
            continue  # a non-list truthy value must not crash the loop
        for d in detail:
            if not isinstance(d, dict):
                continue
            k = _key(row.get("repo"), row.get("pr"), d.get("where"))
            # First writer wins; a location seen twice keeps its first grader.
            index.setdefault(
                k,
                {"grader": grader, "dim": d.get("dim"), "tag": d.get("tag")},
            )
    return index


def join(feedback, ledger_rows=None):
    """Enrich finding-feedback with grader/dim/tag from the run ledger.

    Returns only the finding-outcome records (pr records are dropped here),
    each a shallow copy with `grader`/`dim`/`tag` back-filled from the ledger
    when the record did not carry them. Records with a location absent from the
    ledger keep whatever they self-declared (possibly None).
    """
    index = _ledger_index(ledger_rows)
    out = []
    for r in feedback or []:
        if not isinstance(r, dict) or r.get("kind") == "pr":
            continue
        rec = dict(r)
        hit = index.get(_key(r.get("repo"), r.get("pr"), r.get("where")))
        if hit:
            for field in ("grader", "dim", "tag"):
                if rec.get(field) is None:
                    rec[field] = hit.get(field)
        out.append(rec)
    return out


def _outcome(rec):
    # `outcome` may arrive as a bool/int/None from hand-written or corrupt
    # feedback; coerce non-strings to "" rather than crash on .strip().
    o = rec.get("outcome")
    return o.strip().lower() if isinstance(o, str) else ""


def signal_ratio(ledger):
    """SIGNAL RATIO = acted-on / (acted-on + dismissed) over finding records.

    `ledger` is a list of finding-outcome records (typically the output of
    join()). Rubric-invariant. Returns None when no finding has a determined
    outcome (ratio undefined — do NOT report 0, that reads as "all noise").
    """
    acted = dismissed = 0
    for rec in ledger or []:
        if not isinstance(rec, dict):
            continue
        o = _outcome(rec)
        if o == ACTED_ON:
            acted += 1
        elif o == DISMISSED:
            dismissed += 1
    total = acted + dismissed
    if total == 0:
        return None
    return round(acted / total, 4)


def acted_on_rates(ledger, by="dim"):
    """Per-`by` acted-on rates. `by` ∈ {'dim', 'grader', 'tag'}.

    Returns {key: {acted, dismissed, unknown, determined, rate}} where
    rate = acted / determined (None when determined == 0). Records missing the
    grouping field bucket under '(none)'. This is the drill-down beneath the
    signal ratio: WHICH dimension / grader / failure-class earns its keep.
    """
    if by not in ("dim", "grader", "tag"):
        raise ValueError(f"by must be dim|grader|tag, got {by!r}")
    buckets = {}
    for rec in ledger or []:
        if not isinstance(rec, dict):
            continue
        key = rec.get(by) or "(none)"
        b = buckets.setdefault(key, {"acted": 0, "dismissed": 0, "unknown": 0})
        o = _outcome(rec)
        if o == ACTED_ON:
            b["acted"] += 1
        elif o == DISMISSED:
            b["dismissed"] += 1
        else:
            b["unknown"] += 1
    for b in buckets.values():
        determined = b["acted"] + b["dismissed"]
        b["determined"] = determined
        b["rate"] = round(b["acted"] / determined, 4) if determined else None
    return buckets


def pr_outcomes(feedback):
    """Roll up per-PR outcome records: CI pass-rate and merge-rate.

    Reads the raw feedback (pr records only). Returns
    {prs, ci_passed, ci_pass_rate, merged, merge_rate}. Booleans are read
    leniently (bool/None); an absent field is 'unknown' and left out of that
    field's denominator.
    """
    prs = ci_seen = ci_passed = merge_seen = merged = 0
    for r in feedback or []:
        if not isinstance(r, dict) or r.get("kind") != "pr":
            continue
        prs += 1
        if isinstance(r.get("ci_passed"), bool):
            ci_seen += 1
            ci_passed += 1 if r["ci_passed"] else 0
        if isinstance(r.get("merged"), bool):
            merge_seen += 1
            merged += 1 if r["merged"] else 0
    return {
        "prs": prs,
        "ci_passed": ci_passed,
        "ci_pass_rate": round(ci_passed / ci_seen, 4) if ci_seen else None,
        "merged": merged,
        "merge_rate": round(merged / merge_seen, 4) if merge_seen else None,
    }


def _safe(fn, arg, default):
    """Call fn(arg), degrading ANY exception to `default`.

    trust_metrics promises never to raise, but the underlying readers still
    touch the filesystem — the path can be a directory, unreadable, or hold
    bytes json can't decode. Those are exactly the cases a "safe" surface must
    swallow rather than let the whole CLI crash on one bad file.
    """
    try:
        return fn(arg)
    except Exception:
        return default


def trust_metrics(feedback_path=None, ledger_path=None):
    """The queryable trust surface: signal ratio + rollups + PR outcomes.

    Reads the feedback ledger and joins it to the run ledger (stats.py). Safe on
    empty OR unreadable inputs — every field degrades to None/{} rather than
    raising, and a read that blows up is treated as "no data" (never a crash).
    This is what the `stats` CLI surfaces and what a warehouse view would ingest.
    """
    feedback = _safe(load, feedback_path, default=[])
    ledger_rows = _safe(stats.read_rows, ledger_path, default=[])
    joined = join(feedback, ledger_rows)
    return {
        "signal_ratio": signal_ratio(joined),
        "findings_scored": sum(1 for r in joined if _outcome(r) in _DETERMINED),
        "findings_unknown": sum(1 for r in joined if _outcome(r) == UNKNOWN),
        "by_dimension": acted_on_rates(joined, by="dim"),
        "by_grader": acted_on_rates(joined, by="grader"),
        "by_tag": acted_on_rates(joined, by="tag"),
        "pr_outcomes": pr_outcomes(feedback),
    }
