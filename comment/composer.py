#!/usr/bin/env python3
"""
composer.py — turn a Preflight council JSON result into a PR comment.

Comment v4: a senior-engineer review. Optimized for a 5-second skim, then
progressive detail. Layout, top to bottom:

  marker
  ## Preflight review
  one-line verdict:  🔴 **HOLD** · 33/100 (goal 85) · 3 blockers · 4 nits
  Score breakout table — WHO graded, each grader's dimension sub-scores, so
    the weak axis is obvious at a glance. Mission Control is the gate score.
  Blockers as PR-style suggested changes — each renders like a GitHub review
    comment: file:line + failure-class label + one-line issue, then the
    offending snippet as a code block and a ```suggestion (or a "Change:"
    fenced block) with the fix. Degrades to issue+where+tag when no
    snippet/suggestion is carried.
  Nits: one collapsed <details>, grouped by file. Suggestions render 💡.
  Footer: models used + run artifact link, run trace collapsed.

Contract: findings carry sev, tier, dim, optional tag/say/also/kind, plus
OPTIONAL passthrough `snippet` (offending code) and `suggestion` (the fix;
render as ```suggestion, or a "Change:" fenced block when the finding sets
suggestion_kind == "change"). The score table reads result["grader_scores"]
and result["dimension_scores"] (contract v3); when absent it is computed
from the findings so the table always renders.

Usage:
  python3 comment/composer.py comment/fixtures/pr-92708.json > out.md
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from preflight import dimensions, tags  # noqa: E402

MARKER = "<!-- preflight-council -->"

# Kept for CLI compatibility (the action passes --art-base); no longer
# used — comment v4 embeds no reaction art.
DEFAULT_ART_BASE = (
    "https://raw.githubusercontent.com/jae-ryu/preflight/main/art/reactions/"
)

SEV_RANK = {"high": 0, "med": 1, "low": 2}

REVIEWERS = (("Roaster", "roaster"), ("Mammoth", "mammoth"))

# Score-table presentation: grader glyphs + display names, and the label a
# reader sees for each lane dimension.
GRADER_GLYPH = {"roaster": "🔥", "mammoth": "🦣", "mission_control": "🧑‍🚀"}
GRADER_NAME = {
    "roaster": "Roaster",
    "mammoth": "Mammoth",
    "mission_control": "Mission Control",
}

# A sub-score at or below this is a "work here" axis — rendered bold.
WEAK_DIM = 50

# Fenced-code language by file extension, for offending-code snippets.
EXT_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "ts",
    ".tsx": "tsx",
    ".js": "js",
    ".jsx": "jsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".mojo": "mojo",
}

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
        label = where if not changed else f"{rfile}:{l1}" + (f"-{l2}" if l2 else "")
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


def verdict_headline(verdict, score, goal, blockers=None, nits=None):
    """One skimmable line: dot + verdict + score/goal + counts.

    `🔴 **HOLD** · 33/100 (goal 85) · 3 blockers · 4 nits`
    """
    dot = "🟢" if verdict == "GO" else "🔴"
    line = f"{dot} **{verdict}** · {score}/100 (goal {goal})"
    counts = []
    if blockers is not None:
        counts.append(f"{blockers} blocker{'s' if blockers != 1 else ''}")
    if nits is not None:
        counts.append(f"{nits} nit{'s' if nits != 1 else ''}")
    if counts:
        line += " · " + " · ".join(counts)
    return line


def derive_tier(finding):
    """Contract v2+ has an explicit tier; v1 does not — derive it.

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


def tag_label(finding):
    """Human label for a finding's failure class (`Logic error`, `Other`)."""
    tag = tags.get(derive_tag(finding))
    return tag.label if tag else "Other"


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


def esc(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


# ---------- score breakout table ----------


def _score_data(data):
    """Grader + dimension scores, from the contract or computed on the fly.

    Contract v3 carries `grader_scores` / `dimension_scores`; older results
    do not, so we fall back to computing them from the findings. Mission
    Control's grader score is always the finalized gate score.
    """
    grader = dict(data.get("grader_scores") or {})
    dims = dict(data.get("dimension_scores") or {})
    if not grader or not dims:
        reviewers = data.get("reviewers", {})
        r = reviewers.get("roaster", {}).get("findings", [])
        m = reviewers.get("mammoth", {}).get("findings", [])
        diag = dimensions.breakdown(r, m)
        grader = diag["grader_scores"]
        dims = diag["dimension_scores"]
    grader = dict(grader)
    grader["mission_control"] = data.get("score", 0)
    return grader, dims


def _dim_cell(dims):
    """`correctness **0** · failure-path 100 · …`, weak axes bolded."""
    parts = []
    for name, val in dims.items():
        label = name.replace("_", "-")
        parts.append(f"{label} **{val}**" if val <= WEAK_DIM else f"{label} {val}")
    return " · ".join(parts)


def score_table(data):
    """Markdown table: WHO graded, their score, and per-dimension sub-scores.

    Roaster / Mammoth rows show the lane breakout; the Mission Control row
    is the gate score and carries the verdict arrow.
    """
    grader, dims = _score_data(data)
    verdict = data.get("verdict", "HOLD")
    out = [
        "| Grader | Score | Dimensions |",
        "|:--|:--:|:--|",
    ]
    for key in ("roaster", "mammoth"):
        glyph = GRADER_GLYPH[key]
        name = GRADER_NAME[key]
        sc = grader.get(key, 0)
        cell = _dim_cell(dims.get(key, {}))
        out.append(f"| {glyph} {name} | {sc} | {cell} |")
    mc = grader.get("mission_control", data.get("score", 0))
    out.append(
        f"| {GRADER_GLYPH['mission_control']} "
        f"{GRADER_NAME['mission_control']} | **{mc}** | → **{verdict}** |"
    )
    out.append("")
    return out


# ---------- blockers as suggested changes ----------


def _lang_for(where):
    """Fenced-code language for a `where` path, or "" if unknown."""
    path = str(where or "").split(":")[0]
    _, ext = os.path.splitext(path)
    return EXT_LANG.get(ext.lower(), "")


def _blocker_block(f, repo, sha, files):
    """One blocker, rendered like a GitHub review comment.

    Header (file:line · failure class) + one-line issue, then the offending
    snippet and a suggested change when the finding carries them. Degrades
    to header + issue when snippet/suggestion are absent.
    """
    out = []
    loc = chip(f.get("where", ""), repo, sha, files)
    out.append(f"{loc} · **{tag_label(f)}**")
    out.append("")
    out.append(esc(f.get("issue", "")))
    out.append("")

    lang = _lang_for(f.get("where", ""))
    snippet = f.get("snippet")
    if snippet:
        out.append(f"```{lang}".rstrip())
        out += str(snippet).rstrip("\n").split("\n")
        out.append("```")
    suggestion = f.get("suggestion")
    if suggestion:
        # A contiguous replacement -> GitHub ```suggestion. A non-contiguous
        # or multi-hunk fix -> a plain "Change:" fenced block.
        if f.get("suggestion_kind") == "change":
            out.append("Change:")
            out.append(f"```{lang}".rstrip())
        else:
            out.append("```suggestion")
        out += str(suggestion).rstrip("\n").split("\n")
        out.append("```")
    elif not snippet:
        # No code to show — fall back to the prose fix, if any.
        fix = f.get("fix")
        if fix:
            out.append(f"Fix: {esc(fix)}")

    say = f.get("say")
    if say:
        out.append(f"<sub>{f.get('_reviewer', '')}: {esc(say)}</sub>")
    also = f.get("also")
    if also:
        out.append(f"<sub>Mammoth also flagged: {esc(also.get('say', ''))}</sub>")
    out.append("")
    return out


def gating_block(blockers, repo=None, sha=None, files=None):
    """All blockers, each as its own suggested-change block."""
    out = [f"### Blockers ({len(blockers)})", ""]
    for f in blockers:
        out += _blocker_block(f, repo, sha, files)
    return out


# ---------- nits + suggestions ----------


def nits_block(nits, repo=None, sha=None, files=None):
    """ONE collapsed <details>, nits grouped by file, one line each."""
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
        f"<summary>Nits ({len(nits)})</summary>",
        "",
    ]
    for file in sorted(groups):
        out.append(f"`{file}`")
        rows = sorted(
            groups[file],
            key=lambda x: SEV_RANK.get(x.get("sev", "low"), 3),
        )
        for f in rows:
            sev = f.get("sev", "low")
            loc = chip(f.get("where", ""), repo, sha, files)
            out.append(f"- {sev} · {loc} — {esc(f.get('issue', ''))}")
        out.append("")
    out.append("</details>")
    out.append("")
    return out


def suggestions_block(suggestions, repo=None, sha=None, files=None):
    """Collapsed, non-blocking suggestions, each marked 💡."""
    if not suggestions:
        return []
    out = [
        "<details>",
        f"<summary>Suggestions ({len(suggestions)}, non-blocking)</summary>",
        "",
    ]
    for f in suggestions:
        loc = chip(f.get("where", ""), repo, sha, files)
        out.append(f"- 💡 {loc} — {esc(f.get('issue', ''))}")
        say = f.get("say")
        if say:
            out.append(f"  <br><sub>{f.get('_reviewer', '')}: {esc(say)}</sub>")
    out.append("")
    out.append("</details>")
    out.append("")
    return out


# ---------- run trace + footer ----------


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
    del art_base  # comment v4 embeds no reaction art
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
        verdict_headline(verdict, score, goal, len(blockers), len(nits)),
        "",
    ]

    # GO with zero findings: short comment, nothing else.
    if verdict == "GO" and not blockers and not nits and not suggestions:
        out.append(summary or "No blockers, no nits. Ready to merge.")
        out.append("")
        out += footer(meta, run_url, trace, totals)
        return "\n".join(out) + "\n"

    out += score_table(data)

    if summary:
        out.append(esc(summary))
        out.append("")

    if blockers:
        out += gating_block(blockers, repo, sha, files)
    else:
        out.append("No merge-blockers — only the nits below.")
        out.append("")

    out += nits_block(nits, repo, sha, files)
    out += suggestions_block(suggestions, repo, sha, files)

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
    ap.add_argument("--repo", default=None, help="owner/repo for file:line permalinks")
    ap.add_argument("--sha", default=None, help="head sha for file:line permalinks")
    ap.add_argument("--run-url", default=None, help="link to the workflow run artifact")
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
