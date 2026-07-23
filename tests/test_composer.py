"""Composer v4: senior-engineer review — score table, suggested changes."""

import os
import sys

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "comment")),
)
import composer  # noqa: E402


def _result(
    roaster_findings=None,
    mammoth_findings=None,
    score=39,
    goal=85,
    verdict="HOLD",
    top_actions=None,
):
    return {
        "goal": goal,
        "score": score,
        "verdict": verdict,
        "summary": "test summary",
        "top_actions": top_actions or [],
        "reviewers": {
            "roaster": {
                "summary": "r",
                "findings": roaster_findings or [],
                "parse_ok": True,
            },
            "mammoth": {
                "summary": "m",
                "findings": mammoth_findings or [],
                "parse_ok": True,
            },
        },
        "meta": {
            "chunks": 1,
            "skipped_files": [],
            "truncated": False,
            "diff_bytes": 10,
        },
    }


def _f(sev, where, issue, **extra):
    return {
        "sev": sev,
        "where": where,
        "issue": issue,
        "say": "voice",
        "tier": "blocker" if sev == "high" else "nit",
        **extra,
    }


# ---------- headline + counts ----------


def test_verdict_headline_hold():
    line = composer.verdict_headline("HOLD", 33, 85, blockers=3, nits=4)
    assert "**HOLD**" in line
    assert "33/100" in line
    assert "goal 85" in line
    assert "3 blockers" in line
    assert "4 nits" in line
    assert "🔴" in line


def test_verdict_headline_go():
    line = composer.verdict_headline("GO", 92, 85, blockers=0, nits=0)
    assert "**GO**" in line and "92/100" in line
    assert "🟢" in line
    assert "0 blockers" in line


def test_verdict_headline_singular_counts():
    line = composer.verdict_headline("HOLD", 50, 85, blockers=1, nits=1)
    assert "1 blocker ·" in line or line.endswith("1 blocker · 1 nit")
    assert "1 nit" in line
    assert "blockers" not in line and "nits" not in line


# ---------- score breakout table ----------


def test_score_table_from_contract():
    data = _result(score=33, verdict="HOLD")
    data["grader_scores"] = {"roaster": 75, "mammoth": 75}
    data["dimension_scores"] = {
        "roaster": {
            "correctness": 0,
            "failure-path": 100,
            "security": 100,
            "resilience": 100,
        },
        "mammoth": {"repo-fit": 0, "tests": 100, "docs": 100, "maintainability": 100},
    }
    body = "\n".join(composer.score_table(data))
    assert "🔥 Roaster" in body
    assert "🦣 Mammoth" in body
    assert "🧑‍🚀 Mission Control" in body
    assert "→ **HOLD**" in body
    assert "**33**" in body  # mission control gate score
    assert "correctness **0**" in body  # weak axis bolded
    assert "security 100" in body  # clean axis plain
    assert "| Grader | Score | Dimensions |" in body


def test_score_table_computed_when_absent():
    # No grader_scores in the result -> computed from findings.
    data = _result(
        roaster_findings=[_f("high", "a.py:1", "logic bug", tag="logic-error")]
    )
    body = "\n".join(composer.score_table(data))
    assert "🔥 Roaster" in body
    assert "correctness 70" in body  # one high finding: 100-30


# ---------- permalinks ----------


def test_chip_file_line():
    c = composer.chip("server.py:12", repo="jae-ryu/preflight", sha="abc123")
    assert c == (
        "[`server.py:12`](https://github.com/jae-ryu/preflight"
        "/blob/abc123/server.py#L12)"
    )


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
    c = composer.chip("widget_loader.py:5", repo="o/r", sha="sha", files=FILES)
    assert "blob/sha/smoke/widget_loader.py#L5" in c
    assert "`smoke/widget_loader.py:5`" in c  # resolved path in the label


def test_chip_exact_match_links_unchanged_label():
    c = composer.chip("preflight/api.py:10", repo="o/r", sha="sha", files=FILES)
    assert c == (
        "[`preflight/api.py:10`](https://github.com/o/r/blob/sha/preflight/api.py#L10)"
    )


def test_chip_ambiguous_suffix_no_link():
    files = ["a/util.py", "b/util.py"]
    c = composer.chip("util.py:3", repo="o/r", sha="sha", files=files)
    assert c == "`util.py:3`"  # ambiguous -> plain, no link


def test_chip_no_match_no_link():
    c = composer.chip("ghost.py:1", repo="o/r", sha="sha", files=FILES)
    assert c == "`ghost.py:1`"


def test_chip_bare_file_suffix_resolves():
    c = composer.chip("widget_loader.py", repo="o/r", sha="sha", files=FILES)
    assert c == (
        "[`smoke/widget_loader.py`](https://github.com/o/r/blob"
        "/sha/smoke/widget_loader.py)"
    )


def test_chip_symbol_suffix_resolves():
    c = composer.chip(
        "widget_loader.py:load_config", repo="o/r", sha="sha", files=FILES
    )
    assert "blob/sha/smoke/widget_loader.py)" in c
    assert "smoke/widget_loader.py:load_config" in c


# ---------- run trace table ----------


def _trace():
    return [
        {
            "node": "roaster-c1",
            "model": "kimi",
            "duration_ms": 3400,
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 1200,
                "reasoning_tokens": 6800,
            },
            "retries": 0,
            "parse_ok": True,
            "depends_on": [],
        },
        {
            "node": "mission-control",
            "model": "gemma",
            "duration_ms": 820,
            "usage": {
                "prompt_tokens": 300,
                "completion_tokens": 90,
                "reasoning_tokens": 0,
            },
            "retries": 0,
            "parse_ok": True,
            "depends_on": ["roaster-c1"],
        },
    ]


def test_trace_block_renders():
    totals = {
        "wall_ms": 4300,
        "tokens": {"prompt": 800, "completion": 1290, "reasoning": 6800},
    }
    body = "\n".join(composer.trace_block(_trace(), totals))
    assert "Run trace" in body
    assert "`roaster-c1`" in body
    assert "1.2k (+6.8k think)" in body  # completion + reasoning format
    assert "90" in body  # small completion, no think tail
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
    data["totals"] = {
        "wall_ms": 4300,
        "tokens": {"prompt": 800, "completion": 1290, "reasoning": 6800},
    }
    md = composer.compose(data)
    assert "Run trace" in md
    assert ".png" not in md  # no mascot / reaction art of any kind
    assert ".gif" not in md
    assert "<img" not in md


# ---------- sobriety: no slop signals ----------


def test_no_hype_words():
    # The score table intentionally uses 🔥/🦣/🧑‍🚀 and "Mission Control";
    # what stays banned is hype/marketing language and heading-decoration.
    data = _result(
        roaster_findings=[_f("high", "f.py:1", "crash")],
        mammoth_findings=[
            _f("med", "g.py:2", "nit"),
            _f("low", "h.py:3", "idea", kind="suggestion"),
        ],
    )
    data["trace"] = _trace()
    md = composer.compose(data, run_url="https://example.com/run/1")
    for banned in (
        "🚧",
        "🧹",
        "🎯",
        "⬆️",
        "Bottom line",
        "Fastest path",
        "cleared for launch",
    ):
        assert banned not in md, banned
    # exactly one status marker (the verdict dot)
    assert md.count("🔴") == 1
    assert "## Preflight review" in md


def test_reviewer_names_plain():
    data = _result(roaster_findings=[_f("high", "f.py:1", "crash")])
    md = composer.compose(data)
    assert "Roaster: voice" in md


# ---------- blockers as suggested changes ----------


def test_gating_shows_tag_label_and_issue():
    blk = [
        _f("high", "a.py:1", "socket never closed", tag="resource-leak"),
        _f("high", "c.py:3", "secrets in logs", tag="info-leak"),
    ]
    for b in blk:
        b["_reviewer"] = "Roaster"
    body = "\n".join(composer.gating_block(blk))
    assert "Blockers (2)" in body
    assert "**Resource leak**" in body
    assert "**Information leak**" in body
    assert "socket never closed" in body


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


def test_blocker_snippet_and_suggestion_render():
    f = _f(
        "high",
        "omni.py:110",
        "case-sensitive == rejects every valid model",
        tag="logic-error",
        snippet="if requested == available:",
        suggestion="if requested.casefold() == available.casefold():",
    )
    f["_reviewer"] = "Roaster"
    body = "\n".join(composer.gating_block([f]))
    assert "```python" in body  # snippet fenced with language
    assert "if requested == available:" in body
    assert "```suggestion" in body  # GitHub suggested change
    assert "casefold()" in body


def test_blocker_suggestion_change_kind_uses_change_block():
    f = _f(
        "high",
        "srv.py:5",
        "needs a guard clause across two spots",
        tag="logic-error",
        snippet="do_thing(x)",
        suggestion="if x is None:\n    return\ndo_thing(x)",
        suggestion_kind="change",
    )
    f["_reviewer"] = "Roaster"
    body = "\n".join(composer.gating_block([f]))
    assert "```suggestion" not in body  # non-contiguous -> Change block
    assert "Change:" in body
    assert "if x is None:" in body


def test_blocker_degrades_without_snippet():
    f = _f(
        "high",
        "a.py:1",
        "no code available here",
        tag="logic-error",
        fix="do the right thing",
    )
    f["_reviewer"] = "Roaster"
    body = "\n".join(composer.gating_block([f]))
    assert "no code available here" in body
    assert "Fix: do the right thing" in body  # prose fix fallback
    assert "```" not in body  # nothing to fence


def test_finding_fix_rendered():
    f = _f("high", "a.py:1", "bug", fix="use casefold()")
    f["_reviewer"] = "Roaster"
    body = "\n".join(composer.gating_block([f]))
    assert "Fix: use casefold()" in body


# ---------- suggestions section ----------


def test_suggestions_section():
    data = _result(
        mammoth_findings=[_f("low", "f.py:1", "could memoize", kind="suggestion")]
    )
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
    md = composer.compose(data, run_url="https://github.com/o/r/actions/runs/42")
    assert "[run artifact](https://github.com/o/r/actions/runs/42)" in md


# ---------- clean GO ----------


def test_go_zero_findings_short():
    data = _result(verdict="GO", score=95)
    md = composer.compose(data)
    assert "**GO**" in md
    assert "Blockers" not in md
    assert "<img" not in md
