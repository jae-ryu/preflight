#!/usr/bin/env python3
"""
composer.py — turn a Preflight council JSON result into a PR comment.

Comment v3: a sober, information-dense scorecard. No mascots, no hype,
minimal emphasis. Layout:

  marker
  ## Preflight review
  one-line verdict:  **HOLD** · 45/100 (goal 85, +40 to clear)
  one-line summary + at-a-glance counts
  Blockers, grouped by failure-class tag (preflight/tags.py), each group
    headed by the tag's one-line impact statement. Reviewer quotes are
    kept but secondary.
  Nits: one collapsed <details>, grouped by file.
  Suggestions: collapsed <details>, non-blocking.
  To clear: checklist with exact rubric deltas per gating fix.
  Run trace: collapsed <details>. Plain footer (models, tokens, run link).

Accepts BOTH contract v1 (no per-finding "tier") and v2. When a finding
has no "tier", the composer derives it deterministically: high-sev =
blocker, med/low = nit. A finding may carry a failure-class via "tag";
absent or unknown tags degrade to a heuristic keyword match, then to the
"other" bucket — never a crash.

Usage:
  python3 comment/composer.py comment/fixtures/pr-92708.json > out.md
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)
from preflight import rubric, tags  # noqa: E402

MARKER = "<!-- preflight-council -->"

# Kept for CLI compatibility (the action passes --art-base); no longer
# used — comment v3 embeds no reaction art.
DEFAULT_ART_BASE = (
    "https://raw.githubusercontent.com/jae-ryu/preflight/main/art/reactions/"
)

SEV_RANK = {"high": 0, "med": 1, "low": 2}

REVIEWERS = (("Roaster", "roaster"), ("Mammoth", "mammoth"))

# Conservative keyword fallback for findings that arrive without a "tag".
# First match wins; anything unmatched buckets under tags.OTHER_ID.
_TAG_KEYWORDS = (
    ("resource-leak", ("never closed", "leak", "leaking")),
    ("build-artifact", ("build artifact", "build/lib", "setuptools")),
    ("missing-tests", ("no test", "missing test", "untested")),
    ("wrong-exception-type", ("environmenterror", "exception type")),
    ("error-path-fidelity", ("swallow", "before checking status")),
    ("logic-error", ("case-sensitive", "off-by-one", "wrong result")),
    ("concurrency", ("race", "thread-safe", "not thread")),
    ("info-leak", ("secret", "credential", "api key")),
)


def score_bar_line(score, goal, width=20):
    """A 20-cell bar with a `|` goal marker and a `(need +N)` tail.

    e.g. `████████░░░░░░░░░|░░`  45/100 · goal 85 (need +40)
    """
    filled = max(0, min(width, round(score / 100 * width)))
    cells = ["█"] * filled + ["░"] * (width - filled)
    gpos = max(0, min(width, round(goal / 100 * width)))
    cells.insert(gpos, "|")  # visual goal marker
    bar = "".join(cells)
    line = f"`{bar}`  {score}/100 · goal {goal}"
    if score < goal:
        line += f" (need +{goal - score})"
    return line


_LINE_RE = re.compile(r"^([^:\s]+):(\d+)(?:-(\d+))?$")


def _resolve_file(file, files):
    """Resolve a finding's file path against the diff's changed-file list.

    Returns (resolved_path_or_None, changed: bool).
      - files is None  -> no resolution info; link optimistically.
      - exact match    -> (path, False).
      - suffix match to exactly ONE changed file -> (resolved, True).
      - ambiguous / no match -> (None, False)  => caller renders plain.
    A wrong link is worse than none.
    """
    if files is None:
        return file, False
    if file in files:
        return file, False
    matches = [f for f in files if f == file or f.endswith("/" + file)]
    if len(matches) == 1:
        return matches[0], True
    return None, False


def chip(where, repo=None, sha=None, files=None):
    """Render a `where` as a code chip, linked to the blob when known.

    Handles `file:line` (#Ln), `file:line-range` (#Ln-Lm), a bare `file`
    (no fragment), and `file:symbol` (links the file, keeps the label).

    When ``files`` (the diff's changed-file list) is given, the file part
    is resolved against it: exact or unique-suffix match links (and a
    suffix match displays the resolved path); ambiguous or unmatched
    paths render as a plain code chip with no link.
    """
    where = str(where or "")
    if not where or not repo or not sha:
        return f"`{where}`"

    def link(path, label, frag=""):
        return f"[`{label}`](https://github.com/{repo}/blob/{sha}/{path}{frag})"

    m = _LINE_RE.match(where)
    if m:
        file, l1, l2 = m.group(1), m.group(2), m.group(3)
        rfile, changed = _resolve_file(file, files)
        if rfile is None:
            return f"`{where}`"
        frag = f"#L{l1}" + (f"-L{l2}" if l2 else "")
        label = (
            where if not changed else f"{rfile}:{l1}" + (f"-{l2}" if l2 else "")
        )
        return link(rfile, label, frag)
    if re.match(r"^[^:\s]+$", where):  # bare file path, no line
        rfile, changed = _resolve_file(where, files)
        if rfile is None:
            return f"`{where}`"
        return link(rfile, where if not changed else rfile)
    m3 = re.match(r"^([^:\s]+):", where)  # file:symbol -> link the file
    if m3:
        file = m3.group(1)
        rfile, changed = _resolve_file(file, files)
        if rfile is None:
            return f"`{where}`"
        label = where if not changed else rfile + where[len(file) :]
        return link(rfile, label)
    return f"`{where}`"


def verdict_headline(verdict, score, goal):
    """One line, one small marker: `🔴 **HOLD** · 45/100 (goal 85, ...)`."""
    if verdict == "GO":
        return f"🟢 **GO** · {score}/100 (goal {goal})"
    tail = f", +{goal - score} to clear" if score < goal else ""
    return f"🔴 **HOLD** · {score}/100 (goal {goal}{tail})"


def derive_tier(finding):
    """Contract v2 has an explicit tier; v1 does not — derive it.

    blocker = any high-sev finding; nit = med/low.
    """
    tier = finding.get("tier")
    if tier in ("blocker", "nit"):
        return tier
    return "blocker" if finding.get("sev") == "high" else "nit"


def derive_tag(finding):
    """Failure-class id for a finding; never raises.

    Explicit valid `tag` wins; else a conservative keyword match on the
    issue text; else the `other` bucket.
    """
    tid = finding.get("tag")
    if tags.get(tid):
        return tid
    text = str(finding.get("issue", "")).lower()
    for tag_id, words in _TAG_KEYWORDS:
        if any(w in text for w in words):
            return tag_id
    return tags.OTHER_ID


def collect(reviewers):
    """Flatten findings from both reviewers, tagging each with reviewer
    identity and a derived tier. Returns (blockers, nits, suggestions),
    each sorted by severity. A finding tagged kind:"suggestion" (and not
    a blocker) goes to suggestions, never gating."""
    blockers, nits, suggestions = [], [], []
    for name, key in REVIEWERS:
        rev = reviewers.get(key, {})
        for f in rev.get("findings", []):
            item = dict(f)
            item["_reviewer"] = name
            if derive_tier(f) == "blocker":
                blockers.append(item)
            elif f.get("kind") == "suggestion":
                suggestions.append(item)
            else:
                nits.append(item)
    key_fn = lambda f: SEV_RANK.get(f.get("sev", "low"), 3)  # noqa: E731
    blockers.sort(key=key_fn)
    nits.sort(key=key_fn)
    suggestions.sort(key=key_fn)
    return blockers, nits, suggestions


def at_a_glance(blockers, nits, suggestions):
    """One quiet counts line: `4 blockers · 5 nits · 1 suggestion`."""

    def n(count, word):
        return f"{count} {word}{'s' if count != 1 else ''}"

    parts = [n(len(blockers), "blocker"), n(len(nits), "nit")]
    if suggestions:
        parts.append(n(len(suggestions), "suggestion"))
    return " · ".join(parts)


def esc(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _finding_lines(f, repo, sha, files):
    """One finding: sev · location — issue, then fix + quote sub-lines."""
    out = []
    sev = f.get("sev", "med")
    loc = chip(f.get("where", ""), repo, sha, files)
    out.append(f"- {sev} · {loc} — {esc(f.get('issue', ''))}")
    fix = f.get("fix")
    if fix:
        out.append(f"  <br>Fix: {esc(fix)}")
    say = f.get("say")
    if say:
        out.append(f"  <br><sub>{f.get('_reviewer', '')}: {esc(say)}</sub>")
    also = f.get("also")
    if also:
        out.append(
            f"  <br><sub>Mammoth (also flagged): "
            f"{esc(also.get('say', ''))}</sub>"
        )
    return out


def gating_block(blockers, repo=None, sha=None, files=None):
    """Blockers grouped by failure-class tag, each group headed by the
    tag label and its one-line impact statement."""
    out = [f"### Blockers ({len(blockers)})", ""]
    groups = {}
    order = []
    for f in blockers:
        tid = derive_tag(f)
        if tid not in groups:
            groups[tid] = []
            order.append(tid)
        groups[tid].append(f)
    for tid in order:
        tag = tags.get(tid)
        label = tag.label if tag else "Other"
        out.append(f"**{label}** — {tags.why(tid)}")
        out.append("")
        for f in groups[tid]:
            out += _finding_lines(f, repo, sha, files)
        out.append("")
    return out


def nits_block(nits, repo=None, sha=None, files=None):
    """ONE collapsed <details>, nits grouped by file in a compact table."""
    if not nits:
        return []

    def file_of(f):
        where = f.get("where", "")
        return where.split(":")[0] if where else "(unknown)"

    groups = {}
    for f in nits:
        groups.setdefault(file_of(f), []).append(f)

    out = [
        "<details>",
        f"<summary>Nits ({len(nits)}) — grouped by file</summary>",
        "",
    ]
    for file in sorted(groups):
        out.append(f"`{file}`")
        out.append("")
        out.append("| Sev | Where | Note |")
        out.append("|:---|:---|:---|")
        rows = sorted(
            groups[file],
            key=lambda x: SEV_RANK.get(x.get("sev", "low"), 3),
        )
        for f in rows:
            sev = f.get("sev", "low")
            loc = chip(f.get("where", ""), repo, sha, files)
            out.append(f"| {sev} | {loc} | {esc(f.get('issue', ''))} |")
        out.append("")
    out.append("</details>")
    out.append("")
    return out


def suggestions_block(suggestions, repo=None, sha=None, files=None):
    """Collapsed, non-blocking suggestions."""
    if not suggestions:
        return []
    out = [
        "<details>",
        f"<summary>Suggestions ({len(suggestions)}, non-blocking)</summary>",
        "",
    ]
    for f in suggestions:
        loc = chip(f.get("where", ""), repo, sha, files)
        out.append(f"- {loc} — {esc(f.get('issue', ''))}")
        say = f.get("say")
        if say:
            out.append(f"  <br><sub>{f.get('_reviewer', '')}: {esc(say)}</sub>")
    out.append("")
    out.append("</details>")
    out.append("")
    return out


def _without(findings, target):
    """Return findings minus the first one matching target by where+issue."""
    out, removed = [], False
    for x in findings:
        if (
            not removed
            and x.get("where") == target.get("where")
            and x.get("issue") == target.get("issue")
        ):
            removed = True
            continue
        out.append(x)
    return out


def raise_the_score(data, blockers, goal):
    """Checklist of gating fixes with the exact rubric delta each recovers.

    `- [ ] Fix X (+12 → 51/100)`. Closes with one honest line when
    clearing all gating still lands below goal.
    """
    reviewers = data.get("reviewers", {})
    r = reviewers.get("roaster", {}).get("findings", [])
    m = reviewers.get("mammoth", {}).get("findings", [])
    current = rubric.rubric_score(r, m)

    out = ["### To clear", ""]
    for f in blockers:
        if f.get("_reviewer") == "Roaster":
            new = rubric.rubric_score(_without(r, f), m)
        else:
            new = rubric.rubric_score(r, _without(m, f))
        delta = new - current
        issue = esc(f.get("issue", "") or f.get("where", ""))
        out.append(f"- [ ] {issue} (+{delta} → {new}/100)")
    out.append("")

    # Honest line: what does clearing ALL gating actually land us at?
    r_rest = [x for x in r if x.get("sev") != "high"]
    m_rest = [x for x in m if x.get("sev") != "high"]
    cleared = rubric.rubric_score(r_rest, m_rest)
    if cleared < goal:
        out.append(
            f"Clearing all gating lands ~{cleared}/100 — the nits are "
            f"the rest of the way to {goal}."
        )
        out.append("")
    return out


def _fmt_k(n):
    """Compact token count: 940 -> `940`, 1234 -> `1.2k`."""
    n = int(n or 0)
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _fmt_time(ms):
    """Compact duration: 820 -> `820ms`, 3400 -> `3.4s`."""
    ms = int(ms or 0)
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms}ms"


def _fmt_toks(usage):
    """Tokens cell: `1.2k (+6.8k think)`; drops the think tail when 0."""
    usage = usage or {}
    comp = _fmt_k(usage.get("completion_tokens", 0))
    think = usage.get("reasoning_tokens", 0)
    return f"{comp} (+{_fmt_k(think)} think)" if think else comp


def _totals_line(trace, totals):
    totals = totals or {}
    tok = totals.get("tokens", {}) or {}
    total_tokens = (
        (tok.get("prompt", 0) or 0)
        + (tok.get("completion", 0) or 0)
        + (tok.get("reasoning", 0) or 0)
    )
    return (
        f"{len(trace)} calls · {_fmt_time(totals.get('wall_ms'))} wall "
        f"· {_fmt_k(total_tokens)} tokens"
    )


def trace_block(trace, totals):
    """Collapsed per-call DAG: one row per node, then a totals row."""
    if not trace:
        return []
    out = [
        "<details>",
        "<summary>Run trace</summary>",
        "",
        "| Step | Model | Time | Tokens |",
        "|:---|:---|---:|:---|",
    ]
    for r in trace:
        out.append(
            f"| `{r.get('node', '')}` | `{r.get('model', '')}` "
            f"| {_fmt_time(r.get('duration_ms'))} "
            f"| {_fmt_toks(r.get('usage'))} |"
        )
    out.append(f"| {_totals_line(trace, totals)} | | | |")
    out.append("")
    out.append("</details>")
    out.append("")
    return out


def footer(meta, run_url=None, trace=None, totals=None):
    out = []
    out += trace_block(trace, totals)
    if meta.get("truncated"):
        out.append(
            "<sub>Diff truncated at file boundaries "
            f"({meta.get('diff_bytes', 0):,} bytes) to fit the review "
            "budget.</sub>"
        )
        out.append("")
    chunks = meta.get("chunks")
    if chunks and chunks > 1:
        skipped = meta.get("skipped_files") or []
        note = f"<sub>Reviewed in {chunks} chunks via map-reduce."
        if skipped:
            note += f" Skipped {len(skipped)} low-change file(s)."
        note += "</sub>"
        out.append(note)
        out.append("")
    out.append("---")
    tail = "Preflight council · Kimi K2.6 + Gemma 4 on Modular Cloud"
    if trace:
        tail += f" · {_totals_line(trace, totals)}"
    if run_url:
        tail += f" · [run artifact]({run_url})"
    out.append(f"<sub>{tail}</sub>")
    return out


def compose(
    data,
    art_base=DEFAULT_ART_BASE,  # accepted for compatibility; unused
    repo=None,
    sha=None,
    run_url=None,
    files=None,
):
    del art_base  # comment v3 embeds no reaction art
    goal = data.get("goal", 0)
    score = data.get("score", 0)
    verdict = data.get("verdict", "HOLD")
    summary = data.get("summary", "")
    reviewers = data.get("reviewers", {})
    meta = data.get("meta", {})
    trace = data.get("trace")
    totals = data.get("totals")
    if files is None:
        files = meta.get("changed_files")

    blockers, nits, suggestions = collect(reviewers)

    out = [
        MARKER,
        "## Preflight review",
        "",
        verdict_headline(verdict, score, goal),
        "",
    ]

    # GO with zero findings: short comment, nothing else.
    if verdict == "GO" and not blockers and not nits and not suggestions:
        out.append(summary or "No blockers, no nits. Ready to merge.")
        out.append("")
        out += footer(meta, run_url, trace, totals)
        return "\n".join(out) + "\n"

    if summary:
        out.append(esc(summary))
        out.append("")
    out.append(f"<sub>{at_a_glance(blockers, nits, suggestions)}</sub>")
    out.append("")

    if blockers:
        out += gating_block(blockers, repo, sha, files)
    else:
        out.append("No merge-blockers — only the nits below.")
        out.append("")

    out += nits_block(nits, repo, sha, files)
    out += suggestions_block(suggestions, repo, sha, files)

    if blockers:
        out += raise_the_score(data, blockers, goal)
    else:
        actions = data.get("top_actions", [])
        if actions:
            out.append("### To clear")
            out.append("")
            for a in actions[:3]:
                out.append(f"- [ ] {a}")
            out.append("")

    out += footer(meta, run_url, trace, totals)
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", help="council result JSON")
    ap.add_argument(
        "--art-base",
        default=DEFAULT_ART_BASE,
        help="deprecated; accepted for compatibility, ignored",
    )
    ap.add_argument("-o", "--out", help="write markdown to this file")
    ap.add_argument(
        "--repo", default=None, help="owner/repo for file:line permalinks"
    )
    ap.add_argument(
        "--sha", default=None, help="head sha for file:line permalinks"
    )
    ap.add_argument(
        "--run-url", default=None, help="link to the workflow run artifact"
    )
    ap.add_argument(
        "--files",
        default=None,
        help="comma-separated changed-file list for permalink resolution "
        "(defaults to meta.changed_files in the JSON)",
    )
    args = ap.parse_args()

    with open(args.json_path) as f:
        data = json.load(f)
    files = None
    if args.files is not None:
        files = [p for p in (s.strip() for s in args.files.split(",")) if p]
    md = compose(
        data,
        art_base=args.art_base,
        repo=args.repo,
        sha=args.sha,
        run_url=args.run_url,
        files=files,
    )

    if args.out:
        with open(args.out, "w") as f:
            f.write(md)
    else:
        sys.stdout.write(md)


if __name__ == "__main__":
    main()
