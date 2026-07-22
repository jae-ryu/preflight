"""
The council. Three characters, kept in voice — the voices ARE the product.

  🔥 ROASTER        (Kimi)  — bugs & correctness. Flames the flaw, still helpful.
  🦣 MAMMOTH        (Kimi)  — fine-tooth comb: architecture, tests, docs, consistency.
  🧑‍🚀 MISSION CONTROL (Gemma) — overseer. Weighs both, scores, calls the launch.
"""
import os
import re

from . import api

# Per-character coaching hook. The overseer (or a feedback loop) can shape what a
# reviewer looks for on the NEXT run without editing its charter, by exporting
# PREFLIGHT_{ROASTER,MAMMOTH,MC}_EXTRA. The text is appended as a COACHING block
# to that character's system prompt. Empty/unset = the charter stands unchanged.
_COACH_ENV = {
    "roaster": "PREFLIGHT_ROASTER_EXTRA",
    "mammoth": "PREFLIGHT_MAMMOTH_EXTRA",
    "mission-control": "PREFLIGHT_MC_EXTRA",
}


def coach(system, character):
    """Append this run's coaching block to a character's system prompt, if any."""
    extra = os.environ.get(_COACH_ENV.get(character, ""), "").strip()
    if not extra:
        return system
    return f"{system}\n\nCOACHING FOR THIS RUN (overseer feedback — weigh it):\n{extra}"

# Both reviewers emit the same JSON envelope. Findings feed the deterministic rubric.
# Quality over volume: at most 3 gating problems + 5 nits. Don't spam the PR.
REVIEWER_FMT = (
    'Return ONLY a JSON object: {"summary": "<=12 words, caveman-brief", '
    '"findings": [{"sev":"high|med|low","where":"file:line or area",'
    '"issue":"one line","say":"your in-character one-liner"}]}. '
    'On a med/low finding you MAY add an optional "kind":"suggestion" field to mark '
    "it a non-blocking optimization/refactor idea (never on a high finding). "
    "Report at most 3 gating problems (high sev — things that should block merge) "
    "and at most 5 nits (med/low). If you found more nits, keep only the ones a busy "
    "human would thank you for. Quality over volume — do NOT pad the list. "
    "Most important first. No prose outside the JSON.\n"
    "SEVERITY ANCHORS — choose sev from this table, not vibes:\n"
    "  high = wrong results, crashes, data loss, shared-state corruption, "
    "security, unbounded resource leaks in long-lived code;\n"
    "  med  = leaks/fragility with bounded blast radius, missing tests, "
    "surprising-but-documented behavior;\n"
    "  low  = style, docs, naming."
)

# Post-merge reviewer caps (per reviewer, TOTAL across all chunks).
GATING_CAP = 3
NIT_CAP = 5

_SEV_RANK = {"high": 0, "med": 1, "low": 2}


def _sev_rank(f):
    return _SEV_RANK.get((f.get("sev") or "low").lower(), 2)


def _where_key(f):
    """Normalized `where` key. Strips whitespace and collapses a trailing
    ` / <anything>` so `server.py:_run_query` and `server.py:_run_query / _call_tool`
    map to the same key."""
    w = (f.get("where") or "").lower()
    w = re.sub(r"\s+/\s+.*$", "", w)  # drop " / _other" tail
    return re.sub(r"\s+", "", w)


def _where_file(f):
    """Just the file part of a `where` (everything before the first colon)."""
    key = _where_key(f)
    return key.split(":", 1)[0] if ":" in key else key


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _issue_overlap(f1, f2):
    return _jaccard(_tokens(f1.get("issue")), _tokens(f2.get("issue")))


def _is_file_line(f):
    """True when `where` is a `file:line` or `file:line-range` (numeric line)."""
    parts = _where_key(f).split(":")
    return len(parts) == 2 and re.fullmatch(r"\d+(-\d+)?", parts[1] or "") is not None


def merge_findings(findings_lists, gating_cap=GATING_CAP, nit_cap=NIT_CAP):
    """Merge one reviewer's findings across chunks: concat, dedupe, re-sort, cap.

    - Dedupe near-identical `where` (keep the highest-severity instance).
    - Re-sort by severity (high > med > low), stable within a tier.
    - Keep at most `gating_cap` gating (high) + `nit_cap` nit (med/low) findings.
    """
    flat = [f for lst in findings_lists for f in (lst or []) if isinstance(f, dict)]

    # Dedupe: same normalized `where` key, OR same file with >=0.5 issue-token overlap
    # (catches `server.py:_run_query` vs `server.py:_run_query / _call_tool`).
    deduped = []
    for f in flat:
        dup = None
        for g in deduped:
            same_key = _where_key(f) == _where_key(g)
            same_file = _where_file(f) == _where_file(g)
            if same_key or (same_file and _issue_overlap(f, g) >= 0.5):
                dup = g
                break
        if dup is None:
            deduped.append(f)
        elif _sev_rank(f) < _sev_rank(dup):
            deduped[deduped.index(dup)] = f  # upgrade to the higher-severity duplicate

    # Stable sort by severity — preserves reviewer's most-important-first order within a tier.
    deduped.sort(key=_sev_rank)

    gating = [f for f in deduped if _sev_rank(f) == 0][:gating_cap]
    nits = [f for f in deduped if _sev_rank(f) > 0][:nit_cap]
    return gating + nits


def _cross_match(rf, mf):
    """True when a Roaster and Mammoth finding describe the same issue.

    Match if `where` lines up (exact key, or same file part) AND the issue text
    overlaps >= 0.5; or an exact `file:line` key match with the same line alone.
    """
    if _where_key(rf) == _where_key(mf) and _is_file_line(rf) and _is_file_line(mf):
        return True
    if _where_key(rf) == _where_key(mf) and _issue_overlap(rf, mf) >= 0.5:
        return True
    if _where_file(rf) == _where_file(mf) and _issue_overlap(rf, mf) >= 0.5:
        return True
    return False


def dedupe_cross(roaster, mammoth):
    """Collapse findings both reviewers reported into one finding with both voices.

    Returns (roaster_out, mammoth_out, merged) where a matched pair keeps the
    ROASTER copy (correctness deducts once, never both), attaches
    ``f["also"] = {"who": "mammoth", "say": <mammoth say>}``, and takes the max
    severity of the two. The Mammoth copy is removed from mammoth_out. ``merged``
    is the list of double-flagged findings, for the composer.
    """
    r_findings = list(roaster.get("findings", []))
    m_findings = list(mammoth.get("findings", []))
    m_used = set()
    r_out = []
    merged = []
    for rf in r_findings:
        match_j = None
        for j, mf in enumerate(m_findings):
            if j in m_used:
                continue
            if _cross_match(rf, mf):
                match_j = j
                break
        if match_j is None:
            r_out.append(rf)
            continue
        mf = m_findings[match_j]
        m_used.add(match_j)
        f = dict(rf)
        f["also"] = {"who": "mammoth", "say": mf.get("say", "")}
        if _sev_rank(mf) < _sev_rank(rf):  # keep the more-severe of the two
            f["sev"] = mf.get("sev")
        r_out.append(f)
        merged.append(f)
    m_out = [mf for j, mf in enumerate(m_findings) if j not in m_used]
    roaster_out = {**roaster, "findings": r_out}
    mammoth_out = {**mammoth, "findings": m_out}
    return roaster_out, mammoth_out, merged

ROASTER_SYS = (
    "You are ROASTER, a flame mascot on a code-review crew. You hunt BUGS and "
    "CORRECTNESS problems: logic errors, edge cases that crash, wrong conditions, "
    "races, unhandled failures, resource leaks, security holes. Voice: punchy, "
    "funny, roasts the FLAW not the person, always ends useful. Caveman-brief. "
    "MANDATORY FIRST STEP — before anything else, for EACH changed function: read "
    "its name and signature, state what a caller would expect it to return/do, then "
    "check the code delivers exactly that. A function whose return value or effect "
    "does not match its name is a HIGH finding even if the code has no crash "
    "(example: a load_config that returns a list of key names instead of the "
    "config). Report it as sev high with where=<file>:<def line>. "
    "FAILURE-PATH FIDELITY — for any instrumentation, wrapper, context manager, "
    "try/finally, or error handler (telemetry, logging, spans, dispatch loops), "
    "trace what happens when the wrapped work RAISES, not just when it succeeds: "
    "does the recorded status/span/log/return reflect the failure honestly, or "
    "does it silently close as success, crash the caller, or let a finally-block "
    "mask the original error? Instrumentation that lies on the error path is a "
    "HIGH finding (example: a span left status=OK when its handler threw). "
    "Never report the same root cause twice — pick the sharpest framing. "
    + REVIEWER_FMT
)

MAMMOTH_SYS = (
    "You are MAMMOTH, the ZOOM-OUT reviewer on a code-review crew. Voice: calm, "
    "precise, caveman-brief. You do NOT report pure correctness bugs — that is "
    "Roaster's lane; only overlap when it is genuinely a repo-pattern or design "
    "concern. Your mandate, in priority order:\n"
    "1. Repo fit: does this change repeat or violate patterns used elsewhere in the repo?\n"
    "2. Missing tests: new logic with zero tests is ALWAYS a finding.\n"
    "3. Docs right-sized: flag missing docs AND fluff comments that add noise.\n"
    "4. Maintainability for humans AND agents (names, structure, single-purpose functions).\n"
    "5. Optimization/refactor ideas: emit these with \"kind\":\"suggestion\" so they "
    "render as non-blocking suggestions, never gating.\n"
    + REVIEWER_FMT
)

MC_SYS = (
    "You are MISSION CONTROL, the astronaut overseer of a code-review crew. You get "
    "the ROASTER (bugs/correctness) and MAMMOTH (design/tests) reports. Weigh them "
    "and call the launch.\n"
    "SCORING RUBRIC: start at 100. Blockers (high severity) deduct: correctness "
    "(ROASTER) -12 each; design/tests (MAMMOTH) -8 each. Nits deduct: medium -3, "
    "low -1, with the TOTAL nit deduction capped at -10. Floor 0. Verdict is GO only "
    "if score >= goal AND there are ZERO blockers (any high-severity finding, either "
    "reviewer); otherwise HOLD.\n"
    'Return ONLY a JSON object: {"score": 0-100, "verdict":"GO|HOLD", '
    '"summary":"<=20 words caveman-brief exec summary", '
    '"top_actions":["<=3 concrete fixes to raise the score, highest leverage first"]}. '
    "No prose outside the JSON."
)


def _reviewer(name, system, diff, repo_map=None, node=None):
    """Run one reviewer. Returns (name, {summary, findings, parse_ok}).

    When ``repo_map`` is given (Mammoth's zoom-out context), it is prepended to the
    user prompt as ``REPO MAP:\\n...\\n\\nDIFF:\\n...``. Roaster stays diff-only.
    ``node`` is the trace label for this call (e.g. ``roaster-c1``).
    """
    if repo_map:
        user = f"REPO MAP:\n{repo_map}\n\nDIFF:\n{diff}"
    else:
        user = f"Review this diff:\n\n{diff}"
    data, ok = api.council_call(
        api.REVIEWER_MODEL, coach(system, name), user,
        api.REVIEWER_MAX_TOKENS, node=node)
    if not ok or data is None:
        return name, {"summary": "(could not parse)", "findings": [], "parse_ok": False}
    findings = data.get("findings") or []
    return name, {
        "summary": data.get("summary", ""),
        "findings": [f for f in findings if isinstance(f, dict)],
        "parse_ok": True,
    }


def run_reviewers(diff, executor, repo_map=None):
    """Run ROASTER and MAMMOTH concurrently. Returns (roaster, mammoth) dicts."""
    futs = [
        executor.submit(_reviewer, "roaster", ROASTER_SYS, diff, None, "roaster-c1"),
        executor.submit(_reviewer, "mammoth", MAMMOTH_SYS, diff, repo_map, "mammoth-c1"),
    ]
    reports = {}
    for fut in futs:
        name, rep = fut.result()
        reports[name] = rep
    return reports["roaster"], reports["mammoth"]


def compress_summaries(summaries):
    """Compress several chunk summaries into one <=12-word line via the LIGHT model.

    Falls back to the first non-empty summary (truncated) if the call fails, so a
    flaky compression step never sinks the whole run.
    """
    clean = [s for s in summaries if s]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    joined = " | ".join(clean)
    system = (
        "You compress several short code-review summaries into ONE line of at most "
        "12 words, caveman-brief, capturing the biggest themes. Return ONLY that line, "
        "no quotes, no prose."
    )
    try:
        resp = api.post_chat(api.OVERSEER_MODEL, system,
                             f"Summaries:\n{joined}", 120, temperature=0.3,
                             node="chunk-summary")
        line = (api._message_of(resp).get("content") or "").strip()
        line = line.strip('"').strip()
        if line:
            return " ".join(line.split()[:12])
    except Exception:
        pass
    # Fallback: first summary, trimmed to 12 words.
    return " ".join(clean[0].split()[:12])


def _merge_reviewer(name, reports):
    """Merge one persona's per-chunk reports into a single reviewer dict."""
    parse_ok = any(r["parse_ok"] for r in reports)
    findings = merge_findings([r["findings"] for r in reports])
    summary = compress_summaries([r["summary"] for r in reports if r["parse_ok"]])
    if not parse_ok:
        summary = "(could not parse)"
    return {"summary": summary, "findings": findings, "parse_ok": parse_ok}


def run_reviewers_chunked(chunks, executor, repo_map=None):
    """Map-reduce: each persona reviews every chunk IN PARALLEL, then merge in code.

    Both personas x all chunks are submitted at once to maximize parallelism.
    Returns (roaster, mammoth) merged reviewer dicts.
    """
    tasks = {
        "roaster": [executor.submit(_reviewer, "roaster", ROASTER_SYS, ch, None, f"roaster-c{i + 1}")
                    for i, ch in enumerate(chunks)],
        "mammoth": [executor.submit(_reviewer, "mammoth", MAMMOTH_SYS, ch, repo_map, f"mammoth-c{i + 1}")
                    for i, ch in enumerate(chunks)],
    }
    out = {}
    for name in ("roaster", "mammoth"):
        reports = [fut.result()[1] for fut in tasks[name]]
        out[name] = _merge_reviewer(name, reports)
    return out["roaster"], out["mammoth"]


def run_overseer(goal, roaster, mammoth):
    """Run MISSION CONTROL. Returns (mc_dict, parse_ok)."""
    import json
    packet = json.dumps({"goal": goal, "roaster": roaster, "mammoth": mammoth}, indent=1)
    data, ok = api.council_call(
        api.OVERSEER_MODEL, coach(MC_SYS, "mission-control"),
        f"Goal score is {goal}. Reviewer reports:\n{packet}",
        api.OVERSEER_MAX_TOKENS, node="mission-control")
    if not ok or data is None:
        return {"score": 0, "verdict": "HOLD",
                "summary": "overseer parse fail", "top_actions": []}, False
    return {
        "score": data.get("score", 0),
        "verdict": data.get("verdict", "HOLD"),
        "summary": data.get("summary", ""),
        "top_actions": (data.get("top_actions") or [])[:3],
    }, True
