"""
The council. Three characters, kept in voice — the voices ARE the product.

  🔥 ROASTER        (Kimi)  — bugs & correctness. Flames the flaw, still helpful.
  🦣 MAMMOTH        (Kimi)  — fine-tooth comb: architecture, tests, docs, consistency.
  🧑‍🚀 MISSION CONTROL (Gemma) — overseer. Weighs both, scores, calls the launch.
"""
import re

from . import api

# Both reviewers emit the same JSON envelope. Findings feed the deterministic rubric.
# Quality over volume: at most 3 gating problems + 5 nits. Don't spam the PR.
REVIEWER_FMT = (
    'Return ONLY a JSON object: {"summary": "<=12 words, caveman-brief", '
    '"findings": [{"sev":"high|med|low","where":"file:line or area",'
    '"issue":"one line","say":"your in-character one-liner"}]}. '
    "Report at most 3 gating problems (high sev — things that should block merge) "
    "and at most 5 nits (med/low). If you found more nits, keep only the ones a busy "
    "human would thank you for. Quality over volume — do NOT pad the list. "
    "Most important first. No prose outside the JSON."
)

# Post-merge reviewer caps (per reviewer, TOTAL across all chunks).
GATING_CAP = 3
NIT_CAP = 5

_SEV_RANK = {"high": 0, "med": 1, "low": 2}


def _sev_rank(f):
    return _SEV_RANK.get((f.get("sev") or "low").lower(), 2)


def _where_key(f):
    return re.sub(r"\s+", "", (f.get("where") or "").lower())


def merge_findings(findings_lists, gating_cap=GATING_CAP, nit_cap=NIT_CAP):
    """Merge one reviewer's findings across chunks: concat, dedupe, re-sort, cap.

    - Dedupe near-identical `where` (keep the highest-severity instance).
    - Re-sort by severity (high > med > low), stable within a tier.
    - Keep at most `gating_cap` gating (high) + `nit_cap` nit (med/low) findings.
    """
    flat = [f for lst in findings_lists for f in (lst or []) if isinstance(f, dict)]

    seen = {}
    order = []
    for f in flat:
        key = _where_key(f)
        if key not in seen:
            seen[key] = f
            order.append(key)
        elif _sev_rank(f) < _sev_rank(seen[key]):
            seen[key] = f  # upgrade to the higher-severity duplicate
    deduped = [seen[k] for k in order]

    # Stable sort by severity — preserves reviewer's most-important-first order within a tier.
    deduped.sort(key=_sev_rank)

    gating = [f for f in deduped if _sev_rank(f) == 0][:gating_cap]
    nits = [f for f in deduped if _sev_rank(f) > 0][:nit_cap]
    return gating + nits

ROASTER_SYS = (
    "You are ROASTER, a flame mascot on a code-review crew. You hunt BUGS and "
    "CORRECTNESS problems: logic errors, edge cases that crash, wrong conditions, "
    "races, unhandled failures, resource leaks, security holes. Voice: punchy, "
    "funny, roasts the FLAW not the person, always ends useful. Caveman-brief. "
    + REVIEWER_FMT
)

MAMMOTH_SYS = (
    "You are MAMMOTH, a meticulous mascot on a code-review crew. Fine-tooth comb: "
    "architecture, API/contract design, naming, readability, MISSING TESTS, docs, "
    "and consistency with the surrounding code. Voice: calm, precise, thorough. "
    "Caveman-brief. " + REVIEWER_FMT
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


def _reviewer(name, system, diff):
    """Run one reviewer. Returns (name, {summary, findings, parse_ok})."""
    data, ok = api.council_call(
        api.REVIEWER_MODEL, system, f"Review this diff:\n\n{diff}",
        api.REVIEWER_MAX_TOKENS)
    if not ok or data is None:
        return name, {"summary": "(could not parse)", "findings": [], "parse_ok": False}
    findings = data.get("findings") or []
    return name, {
        "summary": data.get("summary", ""),
        "findings": [f for f in findings if isinstance(f, dict)],
        "parse_ok": True,
    }


def run_reviewers(diff, executor):
    """Run ROASTER and MAMMOTH concurrently. Returns (roaster, mammoth) dicts."""
    futs = [
        executor.submit(_reviewer, "roaster", ROASTER_SYS, diff),
        executor.submit(_reviewer, "mammoth", MAMMOTH_SYS, diff),
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
                             f"Summaries:\n{joined}", 120, temperature=0.3)
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


def run_reviewers_chunked(chunks, executor):
    """Map-reduce: each persona reviews every chunk IN PARALLEL, then merge in code.

    Both personas x all chunks are submitted at once to maximize parallelism.
    Returns (roaster, mammoth) merged reviewer dicts.
    """
    tasks = {
        "roaster": [executor.submit(_reviewer, "roaster", ROASTER_SYS, ch) for ch in chunks],
        "mammoth": [executor.submit(_reviewer, "mammoth", MAMMOTH_SYS, ch) for ch in chunks],
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
        api.OVERSEER_MODEL, MC_SYS,
        f"Goal score is {goal}. Reviewer reports:\n{packet}",
        api.OVERSEER_MAX_TOKENS)
    if not ok or data is None:
        return {"score": 0, "verdict": "HOLD",
                "summary": "overseer parse fail", "top_actions": []}, False
    return {
        "score": data.get("score", 0),
        "verdict": data.get("verdict", "HOLD"),
        "summary": data.get("summary", ""),
        "top_actions": (data.get("top_actions") or [])[:3],
    }, True
