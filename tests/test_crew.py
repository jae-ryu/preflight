"""Cross-reviewer dedupe + self-dedupe (v2.1)."""
from preflight import crew, rubric


def _f(sev, where, issue, say="x"):
    return {"sev": sev, "where": where, "issue": issue, "say": say}


# ---------- self-dedupe in merge_findings ----------

def test_merge_collapses_where_slash_variant():
    # server.py:_run_query vs server.py:_run_query / _call_tool, same bug.
    a = _f("high", "server.py:_run_query",
           "json.loads on non-string raises TypeError not caught")
    b = _f("high", "server.py:_run_query / _call_tool",
           "json.loads on non-string input raises TypeError, not caught")
    out = crew.merge_findings([[a, b]])
    assert len(out) == 1


def test_merge_keeps_distinct_issues_same_file():
    a = _f("med", "server.py:10", "naming is unclear here")
    b = _f("med", "server.py:20", "missing timeout on the socket call entirely")
    out = crew.merge_findings([[a, b]])
    assert len(out) == 2


# ---------- dedupe_cross ----------

def test_cross_exact_line_match():
    r = {"summary": "", "findings": [_f("high", "f.py:12", "off by one in loop")]}
    m = {"summary": "", "findings": [_f("med", "f.py:12", "totally different words here")]}
    r_out, m_out, merged = crew.dedupe_cross(r, m)
    # Exact file:line match collapses even without issue overlap.
    assert len(merged) == 1
    assert len(r_out["findings"]) == 1
    assert m_out["findings"] == []
    assert r_out["findings"][0]["also"]["who"] == "mammoth"


def test_cross_fuzzy_where_match():
    r = {"findings": [_f("high", "server.py:_run_query",
                         "unhandled TypeError from json loads on filters")]}
    m = {"findings": [_f("med", "server.py:_run_query / helper",
                         "json loads TypeError on filters is unhandled here")]}
    r_out, m_out, merged = crew.dedupe_cross(r, m)
    assert len(merged) == 1
    assert m_out["findings"] == []


def test_cross_no_match_keeps_both():
    r = {"findings": [_f("high", "a.py:1", "crash on empty list")]}
    m = {"findings": [_f("med", "b.py:99", "add a docstring to this module")]}
    r_out, m_out, merged = crew.dedupe_cross(r, m)
    assert merged == []
    assert len(r_out["findings"]) == 1
    assert len(m_out["findings"]) == 1


def test_cross_severity_upgraded_to_max():
    # Roaster med + Mammoth high -> kept roaster copy takes the higher severity.
    r = {"findings": [_f("med", "f.py:5", "same root cause described one way")]}
    m = {"findings": [_f("high", "f.py:5", "same root cause described another way")]}
    r_out, m_out, merged = crew.dedupe_cross(r, m)
    assert r_out["findings"][0]["sev"] == "high"


def test_cross_single_deduction_in_rubric():
    # Both flag the same correctness bug. After dedupe the rubric deducts once (-12),
    # not once per reviewer.
    r = {"findings": [_f("high", "f.py:7", "returns None instead of the parsed value")]}
    m = {"findings": [_f("high", "f.py:7", "function returns None not the value it parsed")]}
    r_out, m_out, merged = crew.dedupe_cross(r, m)
    score = rubric.rubric_score(r_out["findings"], m_out["findings"])
    assert score == 88  # 100 - 12 once (kept as roaster correctness), not -20


# ---------- prompt content (iteration 3) ----------

def test_severity_anchors_in_reviewer_prompts():
    for sys in (crew.ROASTER_SYS, crew.MAMMOTH_SYS):
        assert "SEVERITY ANCHORS" in sys
        assert "not vibes" in sys
        assert "shared-state corruption" in sys  # high anchor
        assert "missing tests" in sys            # med anchor


def test_roaster_semantic_intent_mandate():
    s = crew.ROASTER_SYS
    assert "MANDATORY FIRST STEP" in s
    assert "load_config" in s
    assert "does not match its name is a HIGH finding" in s
