#!/usr/bin/env python3
"""
composer.py — turn a Preflight council JSON result into a delightful PR comment.

Comment v2 (see SPEC-V2 "Comment v2"): don't spam PRs. Most critical pieces up
top, a summary of summaries, gating problems visible, nits collapsed and grouped
by file, no laundry lists.

Layout:
  marker
  title
  verdict badge + score bar + Mission Control one-liner (summary of summaries)
  reaction GIF
  1. 🚧 Gating (n)  — visible; the blockers only, one line each, with the
     reviewer's in-character quote as a blockquote under each (max 5 shown).
  2. 🧹 Nits (n)    — ONE collapsed <details>, findings grouped by file. Omitted
     if there are no nits.
  3. ⬆️ Raise the score — top_actions checklist (≤3).
  GO with zero findings: a short congratulatory comment + GO gif, nothing else.

Accepts BOTH contract v1 (no per-finding "tier") and v2. When a finding has no
"tier", the composer derives it deterministically: high-sev = blocker, med/low = nit.

Usage:
  python3 comment/composer.py comment/fixtures/pr-92708.json > out.md
  python3 comment/composer.py result.json --art-base https://raw.githubusercontent.com/jae-ryu/preflight/main/art/reactions/
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from preflight import rubric  # noqa: E402

MARKER = "<!-- preflight-council -->"

# Where reaction GIFs resolve from. In CI the action passes --art-base pointing
# at the raw.githubusercontent.com URL for the Preflight repo.
DEFAULT_ART_BASE = "https://raw.githubusercontent.com/jae-ryu/preflight/main/art/reactions/"

SEV_EMOJI = {"high": "🔴", "med": "🟡", "low": "⚪"}
SEV_RANK = {"high": 0, "med": 1, "low": 2}
# Show every gating item when the deduped total is small; only truncate beyond this.
GATING_VISIBLE_MAX = 4

REVIEWERS = (("🔥", "Roaster", "roaster"), ("🦣", "Mammoth", "mammoth"))


def score_bar(score, width=20):
    filled = max(0, min(width, round(score / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def score_bar_line(score, goal, width=20):
    """A 20-cell bar with a `|` goal marker and a `(need +N)` tail when short.

    e.g. `▓▓▓▓▓▓▓░░░░░░░░░░|░░  39/100 · goal 85 (need +46)`
    """
    filled = max(0, min(width, round(score / 100 * width)))
    cells = ["█"] * filled + ["░"] * (width - filled)
    gpos = max(0, min(width, round(goal / 100 * width)))
    cells.insert(gpos, "|")  # visual goal marker
    bar = "".join(cells)
    line = f"`{bar}`  **{score}/100** &nbsp;·&nbsp; goal **{goal}**"
    if score < goal:
        line += f" **(need +{goal - score})**"
    return line


_LINE_RE = re.compile(r"^([^:\s]+):(\d+)(?:-(\d+))?$")


def _resolve_file(file, files):
    """Resolve a finding's file path against the diff's changed-file list.

    Returns (resolved_path_or_None, changed: bool).
      - files is None  -> no resolution info; link optimistically (path, False).
      - exact match    -> (path, False).
      - suffix match to exactly ONE changed file -> (resolved, True).
      - ambiguous / no match -> (None, False)  => caller renders a plain chip.
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
    """Render a `where` as a code chip, linked to the blob when repo+sha are known.

    Handles `file:line` (#Ln), `file:line-range` (#Ln-Lm), a bare `file` (no
    fragment), and `file:symbol` (links the file, keeps the full label).

    When ``files`` (the diff's changed-file list) is given, the file part is
    resolved against it: exact or unique-suffix match links (and a suffix match
    displays the resolved path); ambiguous or unmatched paths render as a plain
    code chip with no link.
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
    m3 = re.match(r"^([^:\s]+):", where)  # file:symbol -> link the file part
    if m3:
        file = m3.group(1)
        rfile, changed = _resolve_file(file, files)
        if rfile is None:
            return f"`{where}`"
        label = where if not changed else rfile + where[len(file):]
        return link(rfile, label)
    return f"`{where}`"


def verdict_badge(verdict):
    if verdict == "GO":
        return "🟢 **GO** — cleared for launch"
    return "🟠 **HOLD** — not cleared yet"


def verdict_headline(verdict, score, goal):
    """One scannable line: icon + state + score + goal, with the gap to goal."""
    icon = "🟢" if verdict == "GO" else "🟠"
    tail = "" if score >= goal else f" · need **+{goal - score}**"
    return f"### {icon} {verdict} — **{score}/100** · goal {goal}{tail}"


def at_a_glance(blockers, nits, suggestions):
    """A compact counts line so the reader sees the shape before the detail."""
    parts = [f"🚧 **{len(blockers)}** blocker{'s' if len(blockers) != 1 else ''}"]
    parts.append(f"🧹 **{len(nits)}** nit{'s' if len(nits) != 1 else ''}")
    if suggestions:
        parts.append(f"💡 **{len(suggestions)}** suggestion{'s' if len(suggestions) != 1 else ''}")
    return " &nbsp;·&nbsp; ".join(parts)


def pick_band(verdict, score, goal):
    """GO-triumphant / HOLD-close (within 15 of goal) / HOLD-rough."""
    if verdict == "GO":
        return "go-triumphant", "🧑‍🚀 Mission Control: GO for launch!"
    if goal - score <= 15:
        return "hold-close", "🦣 So close — almost there."
    return "hold-rough", "🔥 Oof. Let's regroup."


def derive_tier(finding):
    """Contract v2 has an explicit tier; v1 does not — derive deterministically.

    blocker = any high-sev finding; nit = med/low.
    """
    tier = finding.get("tier")
    if tier in ("blocker", "nit"):
        return tier
    return "blocker" if finding.get("sev") == "high" else "nit"


def collect(reviewers):
    """Flatten findings from both reviewers, tagging each with reviewer identity
    and a derived tier. Returns (blockers, nits, suggestions), each sorted by
    severity. A finding tagged kind:"suggestion" (and not a blocker) goes to
    suggestions, never gating."""
    blockers, nits, suggestions = [], [], []
    for emoji, name, key in REVIEWERS:
        rev = reviewers.get(key, {})
        for f in rev.get("findings", []):
            item = dict(f)
            item["_emoji"] = emoji
            item["_reviewer"] = name
            if derive_tier(f) == "blocker":
                blockers.append(item)
            elif f.get("kind") == "suggestion":
                suggestions.append(item)
            else:
                nits.append(item)
    blockers.sort(key=lambda f: SEV_RANK.get(f.get("sev", "low"), 3))
    nits.sort(key=lambda f: SEV_RANK.get(f.get("sev", "low"), 3))
    suggestions.sort(key=lambda f: SEV_RANK.get(f.get("sev", "low"), 3))
    return blockers, nits, suggestions


def esc(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def gating_block(blockers, repo=None, sha=None, files=None):
    """Visible one-liners for blockers, each with its in-character quote under it.

    Shows every item when there are <= GATING_VISIBLE_MAX; only truncates beyond
    that. A double-flagged finding (has `also`) stacks both voices + a badge."""
    out = ["#### 🚧 Gating ({})".format(len(blockers)), ""]
    shown = blockers if len(blockers) <= GATING_VISIBLE_MAX else blockers[:GATING_VISIBLE_MAX]
    for f in shown:
        dot = SEV_EMOJI.get(f.get("sev", "high"), "🔴")
        issue = esc(f.get("issue", ""))
        out.append(f"{dot} {chip(f.get('where', ''), repo, sha, files)} — {issue}")
        say = f.get("say")
        also = f.get("also")
        if say:
            out.append(f"> {f['_emoji']} **{f['_reviewer']}:** {esc(say)}")
        if also:
            out.append(f"> 🦣 **Mammoth:** {esc(also.get('say', ''))}")
            out.append("> 🔥🦣 **both flagged**")
        out.append("")
    extra = len(blockers) - len(shown)
    if extra > 0:
        out.append(f"> _…and {extra} more gating issue{'s' if extra != 1 else ''} — fix the top ones first._")
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
        f"<summary><b>🧹 Nits ({len(nits)})</b> — collapsed, grouped by file</summary>",
        "",
    ]
    for file in sorted(groups):
        out.append(f"**`{file}`**")
        out.append("")
        out.append("| Sev | Where | Note |")
        out.append("|:---:|:---|:---|")
        for f in sorted(groups[file], key=lambda x: SEV_RANK.get(x.get("sev", "low"), 3)):
            sev = f.get("sev", "low")
            badge = f"{SEV_EMOJI.get(sev, '⚪')} {sev.upper()}"
            issue = esc(f.get("issue", ""))
            out.append(f"| {badge} | {chip(f.get('where', ''), repo, sha, files)} | {issue} |")
        out.append("")
    out.append("</details>")
    out.append("")
    return out


def suggestions_block(suggestions, repo=None, sha=None, files=None):
    """Collapsed, non-blocking 💡 suggestions — framed for people who know the code."""
    if not suggestions:
        return []
    out = [
        "<details>",
        "<summary><b>💡 Suggestions (non-blocking)</b> — for folks who know this code</summary>",
        "",
    ]
    for f in suggestions:
        issue = esc(f.get("issue", ""))
        out.append(f"- {chip(f.get('where', ''), repo, sha, files)} — {issue}")
        say = f.get("say")
        if say:
            out.append(f"  > {f['_emoji']} **{f['_reviewer']}:** {esc(say)}")
    out.append("")
    out.append("</details>")
    out.append("")
    return out


def _without(findings, target):
    """Return findings minus the first one matching target by where+issue."""
    out, removed = [], False
    for x in findings:
        if (not removed and x.get("where") == target.get("where")
                and x.get("issue") == target.get("issue")):
            removed = True
            continue
        out.append(x)
    return out


def raise_the_score(data, blockers, goal):
    """Checklist of gating fixes, each with the exact rubric delta it recovers.

    `- [ ] Fix X (+12 → 51/100)`. Closes with one honest line when clearing all
    gating still lands below goal.
    """
    reviewers = data.get("reviewers", {})
    r = reviewers.get("roaster", {}).get("findings", [])
    m = reviewers.get("mammoth", {}).get("findings", [])
    current = rubric.rubric_score(r, m)

    out = ["#### 🎯 Fastest path to GO", "",
           "_Fix these first — each shows the score it recovers._", ""]
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
            f"_Clearing all gating lands ~{cleared}/100 — the nits are the rest "
            f"of the way to {goal}._")
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
    """Tokens cell: `1.2k (+6.8k think)`; drops the think tail when zero."""
    usage = usage or {}
    comp = _fmt_k(usage.get("completion_tokens", 0))
    think = usage.get("reasoning_tokens", 0)
    return f"{comp} (+{_fmt_k(think)} think)" if think else comp


def trace_block(trace, totals):
    """Collapsed per-call DAG: one row per node, then a totals row."""
    if not trace:
        return []
    out = [
        "<details>",
        "<summary>⏱ Run trace</summary>",
        "",
        "| Step | Model | Time | Tokens |",
        "|:---|:---|---:|:---|",
    ]
    for r in trace:
        out.append(
            f"| `{r.get('node', '')}` | `{r.get('model', '')}` "
            f"| {_fmt_time(r.get('duration_ms'))} | {_fmt_toks(r.get('usage'))} |"
        )
    totals = totals or {}
    tok = totals.get("tokens", {}) or {}
    total_tokens = (tok.get("prompt", 0) or 0) + (tok.get("completion", 0) or 0) \
        + (tok.get("reasoning", 0) or 0)
    line = (f"**{len(trace)} calls · {_fmt_time(totals.get('wall_ms'))} wall "
            f"· {_fmt_k(total_tokens)} tokens**")
    out.append(f"| {line} | | | |")
    out.append("")
    out.append("</details>")
    out.append("")
    return out


def footer(meta, run_url=None, trace=None, totals=None):
    out = []
    out += trace_block(trace, totals)
    if run_url:
        out.append(f"<sub>📦 run artifact: {run_url}</sub>")
        out.append("")
    if meta.get("truncated"):
        out.append(f"<sub>Diff truncated at file boundaries ({meta.get('diff_bytes', 0):,} bytes) to fit the review budget.</sub>")
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
    out.append("🚀 Preflight council · powered by Modular Cloud (Kimi K2.6 + Gemma 4 + FLUX.2)")
    return out


def compose(data, art_base=DEFAULT_ART_BASE, repo=None, sha=None, run_url=None,
            files=None):
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

    base = art_base.rstrip("/")
    band, band_caption = pick_band(verdict, score, goal)
    art_url = f"{base}/{band}.png"

    blockers, nits, suggestions = collect(reviewers)

    art = f'<img src="{art_url}" alt="{band}" width="180" align="right" />'

    # GO with zero findings: short congratulatory comment, nothing else.
    if verdict == "GO" and not blockers and not nits and not suggestions:
        out = [
            MARKER,
            "## 🚀 Preflight review",
            "",
            verdict_headline(verdict, score, goal),
            "",
            score_bar_line(score, goal),
            "",
            art,
            "",
        ]
        if summary:
            out.append(f"> 🧑‍🚀 **Bottom line:** {summary}")
        else:
            out.append("> 🧑‍🚀 **Bottom line:** Clean sweep — no blockers, no nits. Cleared for launch. 🎉")
        out.append("")
        out.append("Nothing for the crew to gripe about. Ship it. 🚀")
        out.append("")
        out += footer(meta, run_url, trace, totals)
        return "\n".join(out) + "\n"

    # --- Digest first (scannable), details after (navigable) ---
    out = [MARKER, "## 🚀 Preflight review", ""]
    out.append(verdict_headline(verdict, score, goal))
    out.append("")
    out.append(art)
    out.append(score_bar_line(score, goal))
    out.append("")
    out.append(at_a_glance(blockers, nits, suggestions))
    out.append("")
    if summary:
        out.append(f"> 🧑‍🚀 **Bottom line:** {summary}")
        out.append("")

    # Lead with what to DO — the fastest path to GO, each fix showing its score.
    if blockers:
        out += raise_the_score(data, blockers, goal)
    else:
        actions = data.get("top_actions", [])
        if actions:
            out.append("#### 🎯 Raise the score")
            out.append("")
            for a in actions[:3]:
                out.append(f"- [ ] {a}")
            out.append("")

    out.append("---")
    out.append("")

    # Blocker detail — the crew's own words + exact locations.
    if blockers:
        out += gating_block(blockers, repo, sha, files)
    else:
        out.append("#### ✅ No blockers")
        out.append("")
        out.append("_Nothing blocks merge — only the nits below._")
        out.append("")

    # Collapsed depth: nits by file, non-blocking suggestions.
    out += nits_block(nits, repo, sha, files)
    out += suggestions_block(suggestions, repo, sha, files)

    out += footer(meta, run_url, trace, totals)
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", help="council result JSON")
    ap.add_argument("--art-base", default=DEFAULT_ART_BASE,
                    help="base URL/path for reaction GIFs")
    ap.add_argument("-o", "--out", help="write markdown to this file")
    ap.add_argument("--repo", default=None, help="owner/repo for file:line permalinks")
    ap.add_argument("--sha", default=None, help="head sha for file:line permalinks")
    ap.add_argument("--run-url", default=None, help="link to the workflow run artifact")
    ap.add_argument("--files", default=None,
                    help="comma-separated changed-file list for permalink resolution "
                         "(defaults to meta.changed_files in the JSON)")
    args = ap.parse_args()

    with open(args.json_path) as f:
        data = json.load(f)
    files = None
    if args.files is not None:
        files = [p for p in (s.strip() for s in args.files.split(",")) if p]
    md = compose(data, art_base=args.art_base, repo=args.repo, sha=args.sha,
                 run_url=args.run_url, files=files)

    if args.out:
        with open(args.out, "w") as f:
            f.write(md)
    else:
        sys.stdout.write(md)


if __name__ == "__main__":
    main()
