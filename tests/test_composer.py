"""Composer v3: sober scorecard — tag grouping, permalinks, deltas, trace."""

import os
import sys

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "comment")),
)
import composer  # noqa: E402


def _result(roaster_findings=None, mammoth_findings=None, score=39, goal=85,
            verdict="HOLD", top_actions=None):
    return {
        "goal": goal, "score": score, "verdict": verdict,
        "summary": "test summary", "top_actions": top_actions or [],
        "reviewers": {
            "roaster": {"summary": "r", "findings": roaster_findings or [],
                        "parse_ok": True},
            "mammoth": {"summary": "m", "findings": mammoth_findings or [],
                        "parse_ok": True},
        },
        "meta": {"chunks": 1, "skipped_files": [], "truncated": False,
                 "diff_bytes": 10},
    }


def _f(sev, where, issue, **extra):
    return {"sev": sev, "where": where, "issue": issue, "say": "voice",
            "tier": "blocker" if sev == "high" else "nit", **extra}


# ---------- headline + score bar ----------

def test_verdict_headline_hold():
    line = composer.verdict_headline("HOLD", 71, 85)
    assert "**HOLD**" in line
    assert "71/100" in line
    assert "goal 85" in line
    assert "+14 to clear" in line


def test_verdict_headline_go():
    line = composer.verdict_headline("GO", 92, 85)
    assert "**GO**" in line and "92/100" in line
    assert "to clear" not in line


def test_goal_marker_and_need():
    line = composer.score_bar_line(39, 85)
    assert "|" in line              # goal marker glyph present
    assert "39/100" in line
    assert "goal 85" in line
    assert "need +46" in line


def test_no_need_when_at_or_above_goal():
    assert "need" not in composer.score_bar_line(90, 85)


def test_at_a_glance_counts():
    line = composer.at_a_glance([1, 2], [3], [])
    assert line == "2 blockers · 1 nit"
    assert "1 suggestion" in composer.at_a_glance([], [], [4])


# ---------- permalinks ----------

def test_chip_file_line():
    c = composer.chip("server.py:12", repo="jae-ryu/preflight", sha="abc123")
    assert c == ("[`server.py:12`](https://github.com/jae-ryu/preflight"
                 "/blob/abc123/server.py#L12)")


def test_chip_line_range():
    c = composer.chip("a.py:10-15", repo="o/r", sha="deadbeef")
    assert "#L10-L15" in c


def test_chip_no_line():
    c = composer.chip("Makefile", repo="o/r", sha="sha")
    assert c == "[`Makefile`](https://github.com/o/r/blob/sha/Makefile)"
    assert "#L" not in c


def test_chip_plain_when_no_repo():
    assert composer.chip("server.py:12") == "`server.py:12`"


# ---------- permalink suffix resolution ----------

FILES = ["smoke/widget_loader.py", "preflight/api.py"]


def test_chip_suffix_resolves_and_shows_resolved_path():
    c = composer.chip("widget_loader.py:5", repo="o/r", sha="sha",
                      files=FILES)
    assert "blob/sha/smoke/widget_loader.py#L5" in c
    assert "`smoke/widget_loader.py:5`" in c  # resolved path in the label


def test_chip_exact_match_links_unchanged_label():
    c = composer.chip("preflight/api.py:10", repo="o/r", sha="sha",
                      files=FILES)
    assert c == ("[`preflight/api.py:10`](https://github.com/o/r/blob/sha"
                 "/preflight/api.py#L10)")


def test_chip_ambiguous_suffix_no_link():
    files = ["a/util.py", "b/util.py"]
    c = composer.chip("util.py:3", repo="o/r", sha="sha", files=files)
    assert c == "`util.py:3`"  # ambiguous -> plain, no link


def test_chip_no_match_no_link():
    c = composer.chip("ghost.py:1", repo="o/r", sha="sha", files=FILES)
    assert c == "`ghost.py:1`"


def test_chip_bare_file_suffix_resolves():
    c = composer.chip("widget_loader.py", repo="o/r", sha="sha", files=FILES)
    assert c == ("[`smoke/widget_loader.py`](https://github.com/o/r/blob"
                 "/sha/smoke/widget_loader.py)")


def test_chip_symbol_suffix_resolves():
    c = composer.chip("widget_loader.py:load_config", repo="o/r", sha="sha",
                      files=FILES)
    assert "blob/sha/smoke/widget_loader.py)" in c
    assert "smoke/widget_loader.py:load_config" in c


# ---------- run trace table ----------

def _trace():
    return [
        {"node": "roaster-c1", "model": "kimi", "duration_ms": 3400,
         "usage": {"prompt_tokens": 500, "completion_tokens": 1200,
                   "reasoning_tokens": 6800},
         "retries": 0, "parse_ok": True, "depends_on": []},
        {"node": "mission-control", "model": "gemma", "duration_ms": 820,
         "usage": {"prompt_tokens": 300, "completion_tokens": 90,
                   "reasoning_tokens": 0},
         "retries": 0, "parse_ok": True, "depends_on": ["roaster-c1"]},
    ]


def test_trace_block_renders():
    totals = {"wall_ms": 4300,
              "tokens": {"prompt": 800, "completion": 1290,
                         "reasoning": 6800}}
    body = "\n".join(composer.trace_block(_trace(), totals))
    assert "Run trace" in body
    assert "`roaster-c1`" in body
    assert "1.2k (+6.8k think)" in body   # completion + reasoning format
    assert "90" in body                   # small completion, no think tail
    assert "2 calls" in body
    assert "4.3s wall" in body
    # total tokens = 800+1290+6800 = 8890 -> 8.9k
    assert "8.9k tokens" in body


def test_trace_block_empty_when_absent():
    assert composer.trace_block(None, None) == []
    assert composer.trace_block([], {}) == []


def test_compose_embeds_trace_no_art():
    data = _result(roaster_findings=[_f("high", "f.py:1", "bug")])
    data["trace"] = _trace()
    data["totals"] = {"wall_ms": 4300,
                      "tokens": {"prompt": 800, "completion": 1290,
                                 "reasoning": 6800}}
    md = composer.compose(data)
    assert "Run trace" in md
    assert ".png" not in md      # no mascot / reaction art of any kind
    assert ".gif" not in md
    assert "<img" not in md


# ---------- sobriety: no slop signals ----------

def test_no_hype_or_heading_emoji():
    data = _result(
        roaster_findings=[_f("high", "f.py:1", "crash")],
        mammoth_findings=[_f("med", "g.py:2", "nit"),
                          _f("low", "h.py:3", "idea", kind="suggestion")])
    data["trace"] = _trace()
    md = composer.compose(data, run_url="https://example.com/run/1")
    for banned in ("🚀", "🧑‍🚀", "🔥", "🦣", "🚧", "🧹", "🎯", "💡", "⬆️",
                   "Bottom line", "Fastest path", "cleared for launch",
                   "Mission Control"):
        assert banned not in md, banned
    # at most one status marker (the verdict dot)
    assert md.count("🔴") <= 1
    assert "## Preflight review" in md


def test_reviewer_names_plain():
    data = _result(roaster_findings=[_f("high", "f.py:1", "crash")])
    md = composer.compose(data)
    assert "Roaster: voice" in md


# ---------- blockers grouped by tag ----------

def test_gating_groups_by_tag_with_why():
    blk = [
        _f("high", "a.py:1", "socket never closed", tag="resource-leak"),
        _f("high", "b.py:2", "another handle leak", tag="resource-leak"),
        _f("high", "c.py:3", "secrets in logs", tag="info-leak"),
    ]
    for b in blk:
        b["_reviewer"] = "Roaster"
    body = "\n".join(composer.gating_block(blk))
    assert "Blockers (3)" in body
    assert "**Resource leak**" in body
    assert body.count("**Resource leak**") == 1  # one heading per tag
    assert "**Information leak**" in body
    assert "never released" in body  # why() line surfaced


def test_gating_unknown_tag_buckets_other():
    f = _f("high", "a.py:1", "something odd", tag="not-a-real-tag")
    f["_reviewer"] = "Roaster"
    body = "\n".join(composer.gating_block([f]))
    assert "**Other**" in body
    assert "something odd" in body


def test_gating_missing_tag_never_crashes():
    f = _f("high", "a.py:1", "connection leaking under load")
    f["_reviewer"] = "Mammoth"
    body = "\n".join(composer.gating_block([f]))
    assert "connection leaking under load" in body


def test_gating_shows_all_blockers():
    blk = [_f("high", "f.py:%d" % i, "bug %d" % i) for i in range(6)]
    for b in blk:
        b["_reviewer"] = "Roaster"
    body = "\n".join(composer.gating_block(blk))
    for i in range(6):
        assert "bug %d" % i in body


def test_finding_fix_rendered():
    f = _f("high", "a.py:1", "bug", fix="use casefold()")
    f["_reviewer"] = "Roaster"
    body = "\n".join(composer.gating_block([f]))
    assert "Fix: use casefold()" in body


# ---------- deltas ----------

def test_raise_the_score_deltas():
    data = _result(roaster_findings=[_f("high", "f.py:1", "crash")],
                   mammoth_findings=[_f("high", "g.py:2", "no test")],
                   score=80)
    blockers, _, _ = composer.collect(data["reviewers"])
    lines = composer.raise_the_score(data, blockers, goal=85)
    body = "\n".join(lines)
    assert "+12 → 92/100" in body   # roaster correctness recovers 12
    assert "+8 → 88/100" in body    # mammoth design recovers 8


def test_clearing_all_gating_honest_line():
    data = _result(
        roaster_findings=[_f("high", "f.py:1", "crash"),
                          _f("high", "f.py:2", "leak")],
        mammoth_findings=[_f("med", "g.py:3", "nit")], score=40)
    blockers, _, _ = composer.collect(data["reviewers"])
    body = "\n".join(composer.raise_the_score(data, blockers, goal=85))
    # clearing both highs -> 100 - 3 (med) = 97 >= 85: no under-goal line.
    assert "Clearing all gating" not in body


def test_clearing_all_gating_still_short():
    data = _result(
        roaster_findings=[_f("high", "f.py:1", "crash")],
        mammoth_findings=[_f("med", "g.py:%d" % i, "n") for i in range(5)],
        score=40)
    blockers, _, _ = composer.collect(data["reviewers"])
    body2 = "\n".join(composer.raise_the_score(data, blockers, goal=95))
    assert "Clearing all gating lands ~90/100" in body2


# ---------- suggestions section ----------

def test_suggestions_section():
    data = _result(mammoth_findings=[
        _f("low", "f.py:1", "could memoize", kind="suggestion")])
    blockers, nits, suggestions = composer.collect(data["reviewers"])
    assert len(suggestions) == 1 and len(nits) == 0
    md = composer.compose(data)
    assert "Suggestions (1, non-blocking)" in md
    assert "could memoize" in md


# ---------- double-flag note ----------

def test_double_flag_note():
    f = _f("high", "f.py:1", "shared bug")
    f["_reviewer"] = "Roaster"
    f["also"] = {"who": "mammoth", "say": "mammoth voice here"}
    body = "\n".join(composer.gating_block([f]))
    assert "also flagged" in body
    assert "mammoth voice here" in body


# ---------- run artifact footer ----------

def test_run_artifact_footer():
    data = _result(roaster_findings=[_f("high", "f.py:1", "bug")])
    md = composer.compose(
        data, run_url="https://github.com/o/r/actions/runs/42")
    assert "[run artifact](https://github.com/o/r/actions/runs/42)" in md


# ---------- clean GO ----------

def test_go_zero_findings_short():
    data = _result(verdict="GO", score=95)
    md = composer.compose(data)
    assert "**GO**" in md
    assert "Blockers" not in md
    assert "<img" not in md
