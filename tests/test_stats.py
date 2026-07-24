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


def test_rows_carry_rubric_version():
    result = dict(RESULT)
    result["rubric_version"] = 1
    rows = stats.rows_for_run(result)
    assert all(r["rubric_version"] == 1 for r in rows)


def test_read_rows_round_trips_and_tolerates_corruption(tmp_path):
    led = tmp_path / "ledger.jsonl"
    stats.append(RESULT, diff=DIFF, repo="o/r", pr="1", ts="T", ledger=str(led))
    with open(led, "a") as f:
        f.write("not json\n")  # a half-written line must not kill the reader
    rows = stats.read_rows(str(led))
    assert len(rows) == 3  # 3 characters, corrupt line skipped
    assert stats.read_rows(str(tmp_path / "missing.jsonl")) == []


def test_read_rows_tolerates_unreadable_ledger(tmp_path):
    """An unreadable ledger (a directory here) degrades to [] rather than
    raising — the council flagged summarize/trust_metrics crashing on this."""
    as_dir = tmp_path / "ledger_is_a_dir"
    as_dir.mkdir()
    assert stats.read_rows(str(as_dir)) == []
    assert stats.summarize(str(as_dir)) == {}


def test_reviewer_row_survives_non_dict_findings():
    """Malformed LLM output (bare string/None in findings) must not crash stats."""
    row = stats._reviewer_row([{"sev": "high", "issue": "real"}, "garbage", None])
    assert row["findings"] == 1  # only the real dict counted
    assert row["blockers"] == 1
    assert len(row["findings_detail"]) == 1


def test_append_and_summarize(tmp_path):
    ledger = str(tmp_path / "s.jsonl")
    stats.append(RESULT, diff=DIFF, repo="o/r", pr="1", ts="T", ledger=ledger)
    stats.append(RESULT, diff=DIFF, repo="o/r", pr="2", ts="T", ledger=ledger)
    agg = stats.summarize(ledger=ledger)
    assert agg["roaster"]["prs_reviewed"] == 2
    assert agg["roaster"]["blockers"] == 2  # 1 per run x 2 runs
    assert agg["roaster"]["loc_reviewed"] == 6  # 3 change-lines x 2 runs
    assert agg["mission-control"]["prs_reviewed"] == 2
