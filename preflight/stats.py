"""
stats.py — per-character telemetry for the council.

Every run, we derive one row per crew member (🔥 Roaster, 🦣 Mammoth,
🧑‍🚀 Mission Control) and append it to a JSONL ledger. These rows are the raw
material for the "how the crew works" sibling view of the council charter:
how many PRs each has reviewed, how much code, how harsh, how fast, how many
tokens (incl. reasoning) they burn.

The ledger is append-only JSONL (one row per character per run) so it stays
trivially greppable and warehouse-ingestable (see FIN-711 / FIN-629). Nothing
here calls the network — it reads a finished run@3 result dict.
"""

import json
import os

DEFAULT_LEDGER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "runs",
    "reviewer-stats.jsonl",
)


def _resolve(ledger):
    """Ledger path: explicit arg > $PREFLIGHT_STATS_LEDGER > DEFAULT_LEDGER.

    The env override lets tests (and alternate deployments) point the ledger
    somewhere other than the repo's real runs/ file.
    """
    return ledger or os.environ.get("PREFLIGHT_STATS_LEDGER") or DEFAULT_LEDGER


# Severity weights used only as a *harshness* proxy (not the scoring rubric).
_SEV_W = {"high": 3, "med": 1, "low": 0.5}

CHARACTERS = (
    ("roaster", "🔥", "Roaster"),
    ("mammoth", "🦣", "Mammoth"),
    ("mission-control", "🧑‍🚀", "Mission Control"),
)


def diff_loc(diff):
    """(added, removed) real change lines in a unified diff, ignoring +++/--- headers."""
    added = removed = 0
    for line in (diff or "").splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _trace_for(trace, prefix):
    """Sum duration + tokens across every trace node for a character (chunks + repairs)."""
    ms = 0
    completion = reasoning = 0
    for r in trace or []:
        node = r.get("node", "") or ""
        if node == prefix or node.startswith(prefix + "-"):
            ms += r.get("duration_ms", 0) or 0
            u = r.get("usage") or {}
            completion += u.get("completion_tokens", 0) or 0
            reasoning += u.get("reasoning_tokens", 0) or 0
    return ms, completion, reasoning


def _reviewer_row(findings):
    """Findings-derived stats for a reviewer: counts, avg issue length, harshness."""
    # Guard against malformed LLM output (non-dict items), like grader_breakdown.
    findings = [f for f in (findings or []) if isinstance(f, dict)]
    n = len(findings)
    blockers = sum(
        1 for f in findings if f.get("tier") == "blocker" or f.get("sev") == "high"
    )
    suggestions = sum(1 for f in findings if f.get("kind") == "suggestion")
    nits = n - blockers - suggestions
    lengths = [len(str(f.get("issue", ""))) for f in findings]
    avg_len = round(sum(lengths) / n, 1) if n else 0.0
    weight = sum(_SEV_W.get(f.get("sev", "low"), 0.5) for f in findings)
    # run@3 additive: per-finding failure-class breakout so the warehouse can
    # GROUP BY tag / dim for recurrence + auto-graduation without re-parsing.
    findings_detail = [
        {
            "dim": f.get("dim"),
            "tag": f.get("tag"),
            "sev": f.get("sev"),
            "tier": f.get("tier"),
            "where": f.get("where"),
            "kind": f.get("kind"),
        }
        for f in findings
    ]
    return {
        "findings_detail": findings_detail,
        "findings": n,
        "blockers": blockers,
        "nits": max(0, nits),
        "suggestions": suggestions,
        "avg_issue_len": avg_len,
        "harshness": round(weight, 1),  # severity-weighted volume
        "blocker_ratio": round(blockers / n, 2) if n else 0.0,
    }


def rows_for_run(result, diff=None, repo=None, pr=None, ts=None):
    """One stat row per character for a finished run@3 result. Pure/derived."""
    meta = result.get("meta", {}) or {}
    trace = result.get("trace") or []
    added, removed = diff_loc(diff)
    base = {
        "ts": ts,
        "repo": repo,
        "pr": pr,
        "head_sha": result.get("head_sha") or meta.get("head_sha"),
        "goal": result.get("goal"),
        "score": result.get("score"),
        "verdict": result.get("verdict"),
        # run@3 additive diagnostics (present from CONTRACT_VERSION 3 on).
        "rubric_score": result.get("rubric_score"),
        "model_score": result.get("model_score"),
        "grader_scores": result.get("grader_scores"),
        "dimension_scores": result.get("dimension_scores"),
        "diff": {
            "bytes": meta.get("diff_bytes"),
            "changed_files": len(meta.get("changed_files") or []),
            "added": added,
            "removed": removed,
        },
    }
    reviewers = result.get("reviewers", {}) or {}
    rows = []
    for key, emoji, name in CHARACTERS:
        row = dict(base)
        row["character"] = key
        row["emoji"] = emoji
        row["name"] = name
        if key == "mission-control":
            # MC's "harshness" = how far below its own goal it landed the PR.
            gap = (result.get("goal") or 0) - (result.get("score") or 0)
            row.update(
                {
                    "findings": None,
                    "verdict_call": result.get("verdict"),
                    "goal_gap": gap,
                    "harshness": round(max(0, gap) / 100, 2),
                }
            )
        else:
            row.update(_reviewer_row(reviewers.get(key, {}).get("findings", [])))
        ms, comp, reason = _trace_for(trace, key)
        row["duration_ms"] = ms
        row["tokens"] = {"completion": comp, "reasoning": reason}
        rows.append(row)
    return rows


def append(result, diff=None, repo=None, pr=None, ts=None, ledger=None):
    """Append this run's per-character rows to the JSONL ledger. Returns the rows."""
    rows = rows_for_run(result, diff=diff, repo=repo, pr=pr, ts=ts)
    ledger = _resolve(ledger)
    os.makedirs(os.path.dirname(ledger), exist_ok=True)
    # One write() of all rows for this run: on POSIX an append-mode write up to
    # PIPE_BUF is atomic, so concurrent runs interleave whole runs, not lines.
    blob = "".join(json.dumps(row) + "\n" for row in rows)
    with open(ledger, "a") as f:
        f.write(blob)
    return rows


def summarize(ledger=None):
    """Aggregate the ledger into per-character lifetime stats (the charter view)."""
    agg = {}
    ledger = _resolve(ledger)
    if not os.path.exists(ledger):
        return agg
    with open(ledger) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a corrupt/half-written line shouldn't kill the report
            c = row.get("character")
            a = agg.setdefault(
                c,
                {
                    "name": row.get("name"),
                    "emoji": row.get("emoji"),
                    "prs_reviewed": 0,
                    "loc_reviewed": 0,
                    "findings": 0,
                    "blockers": 0,
                    "total_ms": 0,
                    "reasoning_tokens": 0,
                    "_harsh": [],
                    "_avg_len": [],
                },
            )
            a["prs_reviewed"] += 1
            d = row.get("diff") or {}
            a["loc_reviewed"] += (d.get("added") or 0) + (d.get("removed") or 0)
            a["findings"] += row.get("findings") or 0
            a["blockers"] += row.get("blockers") or 0
            a["total_ms"] += row.get("duration_ms") or 0
            a["reasoning_tokens"] += (row.get("tokens") or {}).get("reasoning", 0)
            if row.get("harshness") is not None:
                a["_harsh"].append(row["harshness"])
            if row.get("avg_issue_len"):
                a["_avg_len"].append(row["avg_issue_len"])
    for a in agg.values():
        h, lens = a.pop("_harsh"), a.pop("_avg_len")
        a["avg_harshness"] = round(sum(h) / len(h), 2) if h else 0.0
        a["avg_issue_len"] = round(sum(lens) / len(lens), 1) if lens else 0.0
        a["avg_ms_per_pr"] = (
            round(a["total_ms"] / a["prs_reviewed"]) if a["prs_reviewed"] else 0
        )
    return agg
