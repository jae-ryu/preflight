"""Per-character stats ledger: derivation + aggregation."""
from preflight import stats

RESULT = {
    "goal": 85, "score": 59, "verdict": "HOLD",
    "meta": {"diff_bytes": 4000, "changed_files": ["a.py", "b.py"]},
    "reviewers": {
        "roaster": {"findings": [
            {"sev": "high", "tier": "blocker", "issue": "crash-blind"},
            {"sev": "med", "tier": "nit", "issue": "x"},
        ]},
        "mammoth": {"findings": [
            {"sev": "low", "kind": "suggestion", "issue": "rename"},
        ]},
    },
    "trace": [
        {"node": "roaster-c0", "duration_ms": 1000, "usage": {"completion_tokens": 100, "reasoning_tokens": 5000}},
        {"node": "roaster-c0-repair", "duration_ms": 200, "usage": {"completion_tokens": 10, "reasoning_tokens": 0}},
        {"node": "mammoth-c0", "duration_ms": 800, "usage": {"completion_tokens": 90, "reasoning_tokens": 4000}},
        {"node": "mission-control", "duration_ms": 300, "usage": {"completion_tokens": 50, "reasoning_tokens": 0}},
    ],
}
DIFF = "diff --git a/a.py b/a.py\n+added one\n+added two\n-removed one\n"


def test_rows_one_per_character():
    rows = stats.rows_for_run(RESULT, diff=DIFF, repo="o/r", pr="1", ts="T")
    by = {r["character"]: r for r in rows}
    assert set(by) == {"roaster", "mammoth", "mission-control"}
    # Roaster: 2 findings, 1 blocker, chunk + repair durations summed.
    assert by["roaster"]["findings"] == 2
    assert by["roaster"]["blockers"] == 1
    assert by["roaster"]["duration_ms"] == 1200
    assert by["roaster"]["tokens"]["reasoning"] == 5000
    # Mammoth suggestion counted separately from nits.
    assert by["mammoth"]["suggestions"] == 1
    # MC harshness = normalized goal gap.
    assert by["mission-control"]["goal_gap"] == 26
    # LOC parsed from the diff (2 added, 1 removed).
    assert by["roaster"]["diff"]["added"] == 2
    assert by["roaster"]["diff"]["removed"] == 1


def test_append_and_summarize(tmp_path):
    ledger = str(tmp_path / "s.jsonl")
    stats.append(RESULT, diff=DIFF, repo="o/r", pr="1", ts="T", ledger=ledger)
    stats.append(RESULT, diff=DIFF, repo="o/r", pr="2", ts="T", ledger=ledger)
    agg = stats.summarize(ledger=ledger)
    assert agg["roaster"]["prs_reviewed"] == 2
    assert agg["roaster"]["blockers"] == 2  # 1 per run x 2 runs
    assert agg["roaster"]["loc_reviewed"] == 6  # 3 change-lines x 2 runs
    assert agg["mission-control"]["prs_reviewed"] == 2
