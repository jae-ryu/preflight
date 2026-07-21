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
import sys

MARKER = "<!-- preflight-council -->"

# Where reaction GIFs resolve from. In CI the action passes --art-base pointing
# at the raw.githubusercontent.com URL for the Preflight repo.
DEFAULT_ART_BASE = "https://raw.githubusercontent.com/jae-ryu/preflight/main/art/reactions/"

SEV_EMOJI = {"high": "🔴", "med": "🟡", "low": "⚪"}
SEV_RANK = {"high": 0, "med": 1, "low": 2}
GATING_VISIBLE_MAX = 5

REVIEWERS = (("🔥", "Roaster", "roaster"), ("🦣", "Mammoth", "mammoth"))


def score_bar(score, width=20):
    filled = max(0, min(width, round(score / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def verdict_badge(verdict):
    if verdict == "GO":
        return "🟢 **GO** — cleared for launch"
    return "🟠 **HOLD** — not cleared yet"


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
    and a derived tier. Returns (blockers, nits) each sorted by severity."""
    blockers, nits = [], []
    for emoji, name, key in REVIEWERS:
        rev = reviewers.get(key, {})
        for f in rev.get("findings", []):
            item = dict(f)
            item["_emoji"] = emoji
            item["_reviewer"] = name
            (blockers if derive_tier(f) == "blocker" else nits).append(item)
    blockers.sort(key=lambda f: SEV_RANK.get(f.get("sev", "low"), 3))
    nits.sort(key=lambda f: SEV_RANK.get(f.get("sev", "low"), 3))
    return blockers, nits


def esc(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def gating_block(blockers):
    """Visible one-liners for blockers, each with its in-character quote under it."""
    out = ["#### 🚧 Gating ({})".format(len(blockers)), ""]
    shown = blockers[:GATING_VISIBLE_MAX]
    for f in shown:
        dot = SEV_EMOJI.get(f.get("sev", "high"), "🔴")
        where = f.get("where", "")
        issue = esc(f.get("issue", ""))
        out.append(f"{dot} `{where}` — {issue}")
        say = f.get("say")
        if say:
            out.append(f"> {f['_emoji']} **{f['_reviewer']}:** {esc(say)}")
        out.append("")
    extra = len(blockers) - len(shown)
    if extra > 0:
        out.append(f"> _…and {extra} more gating issue{'s' if extra != 1 else ''} — fix the top ones first._")
        out.append("")
    return out


def nits_block(nits):
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
            where = esc(f.get("where", ""))
            issue = esc(f.get("issue", ""))
            out.append(f"| {badge} | `{where}` | {issue} |")
        out.append("")
    out.append("</details>")
    out.append("")
    return out


def footer(meta):
    out = []
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


def compose(data, art_base=DEFAULT_ART_BASE):
    goal = data.get("goal", 0)
    score = data.get("score", 0)
    verdict = data.get("verdict", "HOLD")
    summary = data.get("summary", "")
    reviewers = data.get("reviewers", {})
    meta = data.get("meta", {})

    base = art_base.rstrip("/")
    band, band_caption = pick_band(verdict, score, goal)
    art_url = f"{base}/{band}.gif"

    blockers, nits = collect(reviewers)

    # GO with zero findings: short congratulatory comment, nothing else.
    if verdict == "GO" and not blockers and not nits:
        out = [
            MARKER,
            "## 🚀 Preflight council review",
            "",
            f"### {verdict_badge(verdict)}",
            "",
            f"`{score_bar(score)}`  **{score}/100** &nbsp;·&nbsp; goal **{goal}**",
            "",
            f'<img src="{art_url}" alt="{band}" width="240" align="right" />',
            "",
        ]
        if summary:
            out.append(f"> 🧑‍🚀 **Mission Control:** {summary}")
        else:
            out.append("> 🧑‍🚀 **Mission Control:** Clean sweep — no blockers, no nits. Cleared for launch. 🎉")
        out.append("")
        out.append("Nothing for the crew to gripe about. Ship it. 🚀")
        out.append("")
        out += footer(meta)
        return "\n".join(out) + "\n"

    out = [MARKER, "## 🚀 Preflight council review", ""]

    # Verdict + score + Mission Control summary-of-summaries.
    out.append(f"### {verdict_badge(verdict)}")
    out.append("")
    out.append(f"`{score_bar(score)}`  **{score}/100** &nbsp;·&nbsp; goal **{goal}**")
    out.append("")
    if summary:
        out.append(f"> 🧑‍🚀 **Mission Control:** {summary}")
        out.append("")

    # Reaction art.
    out.append(f'<img src="{art_url}" alt="{band}" width="240" align="right" />')
    out.append("")

    # 1. Gating (visible).
    if blockers:
        out += gating_block(blockers)
    else:
        out.append("#### ✅ No gating problems")
        out.append("")
        out.append("_No merge-blockers from the crew — only the nits below._")
        out.append("")

    # 2. Nits (collapsed).
    out += nits_block(nits)

    # 3. Raise-the-score checklist.
    actions = data.get("top_actions", [])
    if actions:
        out.append("#### ⬆️ Raise the score")
        out.append("")
        for a in actions[:3]:
            out.append(f"- [ ] {a}")
        out.append("")

    # Footer.
    out += footer(meta)
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", help="council result JSON")
    ap.add_argument("--art-base", default=DEFAULT_ART_BASE,
                    help="base URL/path for reaction GIFs")
    ap.add_argument("-o", "--out", help="write markdown to this file")
    args = ap.parse_args()

    with open(args.json_path) as f:
        data = json.load(f)
    md = compose(data, art_base=args.art_base)

    if args.out:
        with open(args.out, "w") as f:
            f.write(md)
    else:
        sys.stdout.write(md)


if __name__ == "__main__":
    main()
