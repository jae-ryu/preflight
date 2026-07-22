"""
preflight run <diff> --goal N [--json out.json]

Convenes the council against a diff and calls GO / HOLD. Pretty terminal output
(ported from the prototype) plus the FROZEN --json contract.

Exit codes: 0 = GO, 1 = HOLD, 2 = infrastructure failure.
"""
import argparse
import concurrent.futures as cf
import json
import os
import subprocess
import sys

from . import CONTRACT_VERSION, api, chunk, crew, rubric
from .diffcap import DEFAULT_CAP, cap_diff

# --- terminal paint (ported from preflight-showcase/preflight.py) ---
_C = dict(dim="\033[2m", b="\033[1m", r="\033[0m", red="\033[31m", grn="\033[32m",
          yel="\033[33m", cyn="\033[36m", mag="\033[35m")


def paint(s, *k):
    if not sys.stdout.isatty():
        return s
    return "".join(_C[x] for x in k) + s + _C["r"]


def build_repo_map(root=".", max_lines=120):
    """Cheap zoom-out context for Mammoth: `git ls-files` (pruned) + README head.

    Best-effort — returns "" on any failure so a review never depends on it.
    """
    try:
        files = subprocess.run(
            ["git", "-C", root, "ls-files"],
            capture_output=True, text=True, timeout=10,
        ).stdout.splitlines()
    except Exception:
        return ""
    files = [f for f in files if f]
    listing = files[:max_lines]
    parts = ["FILES:"] + listing
    if len(files) > max_lines:
        parts.append(f"...(+{len(files) - max_lines} more files)")
    for readme in ("README.md", "README.rst", "README.txt", "README"):
        path = os.path.join(root, readme)
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    head = [next(fh, "").rstrip("\n") for _ in range(30)]
                parts.append("")
                parts.append(f"README ({readme}, first 30 lines):")
                parts.extend(line for line in head if line is not None)
            except Exception:
                pass
            break
    return "\n".join(parts)


def build_result(diff, goal, cap=DEFAULT_CAP, executor=None, repo_map=None):
    """Run the whole council and assemble the frozen contract dict.

    Returns (result_dict, infra_ok). infra_ok is False when both reviewers failed
    to parse (treated as an infrastructure failure -> exit 2).
    """
    diff_bytes = len(diff.encode())

    # Single-pass for small diffs; per-file map-reduce for big ones.
    if len(diff) <= cap:
        capped, truncated = cap_diff(diff, cap)
        chunk_texts = None
        skipped_files = []
        n_chunks = 1
    else:
        chunk_texts, skipped_files = chunk.chunk_diff(diff)
        truncated = False
        n_chunks = len(chunk_texts)

    own_executor = executor is None
    if own_executor:
        # Chunked runs fan out both personas across every chunk — size the pool to
        # keep them all in flight.
        workers = 2 * max(1, n_chunks) if chunk_texts is not None else 2
        executor = cf.ThreadPoolExecutor(max_workers=min(workers, 16))
    try:
        if chunk_texts is not None:
            roaster, mammoth = crew.run_reviewers_chunked(chunk_texts, executor, repo_map)
        else:
            roaster, mammoth = crew.run_reviewers(capped, executor, repo_map)
    finally:
        if own_executor:
            executor.shutdown(wait=True)

    # Cross-reviewer dedupe: collapse issues both reviewers flagged so the rubric
    # deducts once per unique issue and the composer can show both voices.
    roaster, mammoth, _merged = crew.dedupe_cross(roaster, mammoth)

    # Deterministic tiering (code decides, not the reviewers).
    rubric.apply_tiers(roaster["findings"])
    rubric.apply_tiers(mammoth["findings"])

    mc, _mc_ok = crew.run_overseer(goal, roaster, mammoth)

    final = rubric.finalize(
        mc.get("score", 0), mc.get("verdict", "HOLD"),
        roaster["findings"], mammoth["findings"], goal)

    result = {
        "version": CONTRACT_VERSION,
        "goal": goal,
        "score": final["score"],
        "verdict": final["verdict"],
        "blockers": final["blockers"],
        "nits": final["nits"],
        "summary": mc.get("summary", ""),
        "top_actions": mc.get("top_actions", []),
        "reviewers": {
            "roaster": roaster,
            "mammoth": mammoth,
        },
        "meta": {
            "models": {
                "reviewers": api.REVIEWER_MODEL,
                "overseer": api.OVERSEER_MODEL,
            },
            "diff_bytes": diff_bytes,
            "truncated": truncated,
            "chunks": n_chunks,
            "skipped_files": skipped_files,
        },
    }
    infra_ok = roaster["parse_ok"] or mammoth["parse_ok"]
    return result, infra_ok


def render(result):
    """Pretty terminal render of a result dict (prototype aesthetics)."""
    goal = result["goal"]
    score = result["score"]
    verdict = result["verdict"]
    roaster = result["reviewers"]["roaster"]
    mammoth = result["reviewers"]["mammoth"]

    vcol = "grn" if verdict == "GO" else "yel"
    bar = "█" * (score // 5) + "░" * (20 - score // 5)

    out = []
    out.append("\n" + "═" * 60)
    out.append(f"{paint('  🧑‍🚀 MISSION CONTROL', 'b')} "
               f"{paint(f'— {verdict}', 'b', vcol)}"
               f"{paint(f' ({score}/100, goal {goal})', 'dim')}")
    out.append(f"  {paint(bar, vcol)}")
    blk = result.get("blockers", 0)
    nit = result.get("nits", 0)
    out.append(f"  {paint(f'🚧 {blk} blocker' + ('s' if blk != 1 else ''), 'red' if blk else 'dim')}"
               f"  {paint(f'🧹 {nit} nit' + ('s' if nit != 1 else ''), 'dim')}")
    out.append(f"  {result['summary']}")
    out.append("─" * 60)
    out.append(f"{paint('  🔥 ROASTER ')} {roaster.get('summary', '')}")
    out.append(f"{paint('  🦣 MAMMOTH ')} {mammoth.get('summary', '')}")
    if result.get("top_actions"):
        out.append(paint("\n  ⬆  RAISE THE SCORE", "b"))
        for a in result["top_actions"][:3]:
            out.append(f"     • {a}")
    out.append("═" * 60)

    sevcol = {"high": "red", "med": "yel", "low": "dim"}
    for emoji, name, rep in (("🔥", "ROASTER", roaster), ("🦣", "MAMMOTH", mammoth)):
        findings = rep.get("findings", [])
        if not findings:
            continue
        out.append(f"{paint(f'  {emoji} {name}', 'b')} {paint(f'· {len(findings)} notes', 'dim')}")
        for x in findings:
            sev = (x.get("sev") or "low").lower()
            out.append(f"   {paint(sev.upper().ljust(4), sevcol.get(sev, 'dim'))} "
                       f"{paint(x.get('where', ''), 'cyn')}")
            out.append(f"        {x.get('issue', '')}")
            if x.get("say"):
                out.append(paint(f'        “{x["say"]}”', "dim"))
    out.append("")
    return "\n".join(out)


def _read_diff(src):
    if src == "-":
        return sys.stdin.read()
    with open(src) as f:
        return f.read()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="preflight", description="Council PR reviewer on Modular Cloud.")
    sub = parser.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="review a diff")
    run.add_argument("diff", nargs="?", default="-", help="diff file, or - for stdin")
    run.add_argument("--goal", type=int, default=80, help="repo-owner goal score (default 80)")
    run.add_argument("--json", dest="json_out", metavar="OUT", help="also write the frozen JSON contract here")
    run.add_argument("--cap", type=int, default=DEFAULT_CAP, help=argparse.SUPPRESS)

    # Bare invocation without the "run" subcommand behaves like "run" (prototype-friendly).
    if argv and argv[0] not in ("run", "-h", "--help"):
        argv = ["run"] + argv
    args = parser.parse_args(argv)

    if args.cmd != "run":
        parser.print_help()
        return 2

    if not api.api_key():
        print("set MODULAR_API_KEY", file=sys.stderr)
        return 2

    diff = _read_diff(args.diff)
    if not diff.strip():
        print("empty diff", file=sys.stderr)
        return 2

    print(f"{paint('  🚀 PREFLIGHT', 'b', 'cyn')} {paint('· convening the crew…', 'dim')}")

    try:
        result, infra_ok = build_result(
            diff, args.goal, cap=args.cap, repo_map=build_repo_map())
    except api.APIError as e:
        print(f"infrastructure failure: {e}", file=sys.stderr)
        return 2

    print(render(result))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(result, f, indent=2)
            f.write("\n")

    if not infra_ok:
        print("infrastructure failure: both reviewers unparseable", file=sys.stderr)
        return 2
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
