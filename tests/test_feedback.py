"""Ground-truth feedback: signal ratio, acted-on rollups, PR outcomes, join."""
import json

from preflight import feedback


def _finding(where, outcome, **kw):
    r = {"kind": "finding", "repo": "o/r", "pr": "1", "where": where,
         "outcome": outcome}
    r.update(kw)
    return r


# ---- signal_ratio math -------------------------------------------------------


def test_signal_ratio_basic():
    ledger = [
        _finding("a.py:1", "acted-on"),
        _finding("a.py:2", "acted-on"),
        _finding("a.py:3", "acted-on"),
        _finding("a.py:4", "dismissed"),
    ]
    assert feedback.signal_ratio(ledger) == 0.75


def test_signal_ratio_excludes_unknown_from_denominator():
    ledger = [
        _finding("a.py:1", "acted-on"),
        _finding("a.py:2", "dismissed"),
        _finding("a.py:3", "unknown"),
        _finding("a.py:4", "unknown"),
    ]
    # 1 acted / (1 acted + 1 dismissed) = 0.5; the two unknowns don't dilute it.
    assert feedback.signal_ratio(ledger) == 0.5


def test_signal_ratio_none_when_no_determined_outcomes():
    assert feedback.signal_ratio([]) is None
    assert feedback.signal_ratio([_finding("a.py:1", "unknown")]) is None


def test_signal_ratio_ignores_non_dict_and_bad_outcome():
    ledger = [
        _finding("a.py:1", "acted-on"),
        "garbage",
        {"kind": "finding", "outcome": "maybe"},  # unrecognized -> ignored
        None,
    ]
    assert feedback.signal_ratio(ledger) == 1.0


def test_signal_ratio_tolerates_non_string_outcome():
    # bool/int/None outcome must not crash (council-caught: _outcome AttributeError).
    ledger = [
        _finding("a.py:1", "acted-on"),
        {"kind": "finding", "outcome": True},
        {"kind": "finding", "outcome": 3},
        {"kind": "finding", "outcome": None},
    ]
    assert feedback.signal_ratio(ledger) == 1.0
    # the same non-strings survive the rollup path too.
    rates = feedback.acted_on_rates(ledger, by="dim")
    assert rates["(none)"]["unknown"] == 3


def test_signal_ratio_is_rubric_invariant():
    # No score field anywhere; ratio depends only on outcomes.
    ledger = [_finding("a.py:1", "acted-on", score=99),
              _finding("a.py:2", "dismissed", score=1)]
    assert feedback.signal_ratio(ledger) == 0.5


# ---- acted_on_rates ----------------------------------------------------------


def test_acted_on_rates_by_dim():
    ledger = [
        _finding("a.py:1", "acted-on", dim="correctness"),
        _finding("a.py:2", "dismissed", dim="correctness"),
        _finding("a.py:3", "acted-on", dim="security"),
        _finding("a.py:4", "unknown", dim="security"),
    ]
    rates = feedback.acted_on_rates(ledger, by="dim")
    assert rates["correctness"]["rate"] == 0.5
    assert rates["correctness"]["determined"] == 2
    assert rates["security"]["rate"] == 1.0
    assert rates["security"]["unknown"] == 1


def test_acted_on_rates_by_grader_and_tag():
    ledger = [
        _finding("a.py:1", "acted-on", grader="roaster", tag="logic-error"),
        _finding("a.py:2", "dismissed", grader="mammoth", tag="missing-tests"),
    ]
    by_g = feedback.acted_on_rates(ledger, by="grader")
    assert by_g["roaster"]["rate"] == 1.0
    assert by_g["mammoth"]["rate"] == 0.0
    by_t = feedback.acted_on_rates(ledger, by="tag")
    assert set(by_t) == {"logic-error", "missing-tests"}


def test_acted_on_rates_missing_field_buckets_none():
    rates = feedback.acted_on_rates([_finding("a.py:1", "acted-on")], by="dim")
    assert "(none)" in rates
    assert rates["(none)"]["rate"] == 1.0


def test_acted_on_rates_rate_none_when_only_unknown():
    rates = feedback.acted_on_rates(
        [_finding("a.py:1", "unknown", dim="x")], by="dim"
    )
    assert rates["x"]["rate"] is None
    assert rates["x"]["determined"] == 0


def test_acted_on_rates_bad_by_raises():
    try:
        feedback.acted_on_rates([], by="nope")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


# ---- pr_outcomes -------------------------------------------------------------


def test_pr_outcomes():
    fb = [
        {"kind": "pr", "repo": "o/r", "pr": "1", "ci_passed": True, "merged": True},
        {"kind": "pr", "repo": "o/r", "pr": "2", "ci_passed": False, "merged": False},
        {"kind": "pr", "repo": "o/r", "pr": "3", "ci_passed": True},  # merged unknown
        _finding("a.py:1", "acted-on"),  # not a pr row — ignored
    ]
    out = feedback.pr_outcomes(fb)
    assert out["prs"] == 3
    assert out["ci_pass_rate"] == round(2 / 3, 4)
    assert out["merge_rate"] == 0.5  # only 2 rows had a bool merged


def test_pr_outcomes_empty():
    out = feedback.pr_outcomes([])
    assert out["prs"] == 0
    assert out["ci_pass_rate"] is None
    assert out["merge_rate"] is None


# ---- join to run ledger ------------------------------------------------------


def test_join_backfills_grader_dim_tag_from_ledger():
    ledger_rows = [{
        "repo": "o/r", "pr": "1", "character": "roaster",
        "findings_detail": [
            {"where": "a.py:1", "dim": "correctness", "tag": "logic-error"},
        ],
    }]
    fb = [_finding("a.py:1", "acted-on")]  # minimal: no grader/dim/tag
    joined = feedback.join(fb, ledger_rows)
    assert joined[0]["grader"] == "roaster"
    assert joined[0]["dim"] == "correctness"
    assert joined[0]["tag"] == "logic-error"


def test_join_does_not_overwrite_declared_fields():
    ledger_rows = [{
        "repo": "o/r", "pr": "1", "character": "roaster",
        "findings_detail": [{"where": "a.py:1", "dim": "correctness"}],
    }]
    fb = [_finding("a.py:1", "acted-on", dim="security")]
    joined = feedback.join(fb, ledger_rows)
    assert joined[0]["dim"] == "security"  # self-declared wins


def test_join_drops_pr_rows_and_tolerates_missing_ledger():
    fb = [_finding("a.py:1", "acted-on"),
          {"kind": "pr", "pr": "1", "merged": True}]
    joined = feedback.join(fb, None)
    assert len(joined) == 1
    assert joined[0]["where"] == "a.py:1"


def test_join_unmatched_location_keeps_self_declared():
    joined = feedback.join([_finding("z.py:9", "acted-on")], [])
    assert joined[0].get("grader") is None


# ---- load (JSONL + JSON array + tolerance) -----------------------------------


def test_load_jsonl(tmp_path):
    p = tmp_path / "fb.jsonl"
    p.write_text(
        json.dumps(_finding("a.py:1", "acted-on")) + "\n"
        + "not json\n"  # corrupt line skipped
        + json.dumps(_finding("a.py:2", "dismissed")) + "\n"
    )
    rows = feedback.load(str(p))
    assert len(rows) == 2


def test_load_json_array(tmp_path):
    p = tmp_path / "fb.json"
    p.write_text(json.dumps([_finding("a.py:1", "acted-on"), "junk"]))
    rows = feedback.load(str(p))
    assert len(rows) == 1  # non-dict dropped


def test_load_missing_file_returns_empty(tmp_path):
    assert feedback.load(str(tmp_path / "nope.jsonl")) == []


# ---- trust_metrics end-to-end ------------------------------------------------


def test_trust_metrics_end_to_end(tmp_path, monkeypatch):
    fb = tmp_path / "fb.jsonl"
    fb.write_text("\n".join(json.dumps(r) for r in [
        _finding("a.py:1", "acted-on"),
        _finding("a.py:2", "dismissed"),
        {"kind": "pr", "pr": "1", "ci_passed": True, "merged": True},
    ]))
    led = tmp_path / "ledger.jsonl"
    led.write_text(json.dumps({
        "repo": "o/r", "pr": "1", "character": "roaster",
        "findings_detail": [
            {"where": "a.py:1", "dim": "correctness", "tag": "logic-error"},
            {"where": "a.py:2", "dim": "security", "tag": "info-leak"},
        ],
    }) + "\n")
    m = feedback.trust_metrics(feedback_path=str(fb), ledger_path=str(led))
    assert m["signal_ratio"] == 0.5
    assert m["findings_scored"] == 2
    assert m["by_dimension"]["correctness"]["rate"] == 1.0
    assert m["by_dimension"]["security"]["rate"] == 0.0
    assert m["pr_outcomes"]["merge_rate"] == 1.0


def test_trust_metrics_empty_is_safe(tmp_path):
    m = feedback.trust_metrics(
        feedback_path=str(tmp_path / "none.jsonl"),
        ledger_path=str(tmp_path / "none-ledger.jsonl"),
    )
    assert m["signal_ratio"] is None
    assert m["by_tag"] == {}
    assert m["pr_outcomes"]["prs"] == 0
