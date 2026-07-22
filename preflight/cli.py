"""
preflight run <diff> --goal N [--json out.json]

Convenes the council against a diff and calls GO / HOLD. Pretty terminal output
(ported from the prototype) plus the FROZEN --json contract.

Exit codes: 0 = GO, 1 = HOLD, 2 = infrastructure failure.
"""
import argparse
import concurrent.futures as cf
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

import time

import datetime

from . import CONTRACT_VERSION, api, chunk, config, crew, rubric, stats
from .diffcap import DEFAULT_CAP, cap_diff, changed_files

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


def _base_node(row):
    """Node label with any trailing ``-repair`` suffix removed."""
    n = row.get("node", "") or ""
    return n[:-len("-repair")] if n.endswith("-repair") else n


def _assemble_trace(chunked):
    """Snapshot api.TRACE and wire ``depends_on`` (a cli-layer concern, not api's).

    - reviewer nodes (roaster-c*, mammoth-c*) depend on [] — or ["chunk-split"]
      when the diff was chunked;
    - mission-control depends on every reviewer node;
    - chunk-summary depends on [] (it is fed the reviewer summaries in code).
    """
    trace = [dict(r) for r in api.TRACE]
    reviewer_dep = ["chunk-split"] if chunked else []
    reviewer_nodes = []
    for row in trace:
        base = _base_node(row)
        if base.startswith("roaster-c") or base.startswith("mammoth-c"):
            row["depends_on"] = list(reviewer_dep)
            if not (row.get("node") or "").endswith("-repair"):
                reviewer_nodes.append(row["node"])
    for row in trace:
        base = _base_node(row)
        if base == "mission-control":
            row["depends_on"] = list(reviewer_nodes)
        elif base == "chunk-summary":
            row["depends_on"] = []
    return trace


def _trace_totals(trace, wall_ms):
    """Sum token usage across trace rows + carry the run wall time."""
    prompt = sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in trace)
    completion = sum((r.get("usage") or {}).get("completion_tokens", 0) for r in trace)
    reasoning = sum((r.get("usage") or {}).get("reasoning_tokens", 0) for r in trace)
    return {
        "wall_ms": wall_ms,
        "tokens": {"prompt": prompt, "completion": completion, "reasoning": reasoning},
    }


def build_result(diff, goal, cap=DEFAULT_CAP, executor=None, repo_map=None):
    """Run the whole council and assemble the frozen contract dict.

    Returns (result_dict, infra_ok). infra_ok is False when both reviewers failed
    to parse (treated as an infrastructure failure -> exit 2).
    """
    api.reset_trace()
    wall_start = time.time()
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

    wall_ms = int((time.time() - wall_start) * 1000)
    trace = _assemble_trace(chunked=chunk_texts is not None)
    totals = _trace_totals(trace, wall_ms)

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
        "trace": trace,
        "totals": totals,
        "meta": {
            "models": {
                "reviewers": api.REVIEWER_MODEL,
                "overseer": api.OVERSEER_MODEL,
            },
            "diff_bytes": diff_bytes,
            "truncated": truncated,
            "chunks": n_chunks,
            "skipped_files": skipped_files,
            "changed_files": changed_files(diff),
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


# --- `preflight review <pr>`: the one-command entrypoint --------------------
# Fetch a live PR, run the council, compose the comment, and (optionally) post
# it — the whole thing in a single call. gh is the seam for GitHub I/O so tests
# can stub it; posting is opt-in (--post) because it writes to a real PR.

def _gh(args, stdin=None):
    """Run `gh <args>` and return stdout. Raises APIError on any failure."""
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, input=stdin)
    except FileNotFoundError:
        raise api.APIError("gh CLI not found — install GitHub CLI to use `preflight review`")
    if p.returncode != 0:
        raise api.APIError(f"gh {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def _repo_slug_from_url(url):
    """`https://github.com/owner/repo/pull/12` -> `owner/repo` (or None)."""
    m = re.search(r"github\.com/([^/]+/[^/]+)/pull/", url or "")
    return m.group(1) if m else None


def _fetch_pr(pr, repo=None):
    """Return (diff, head_sha, changed_files, repo_slug) for a PR via gh."""
    repo_args = ["--repo", repo] if repo else []
    diff = _gh(["pr", "diff", str(pr), *repo_args])
    raw = _gh(["pr", "view", str(pr), *repo_args, "--json", "headRefOid,files,url"])
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError as e:
        raise api.APIError(f"could not parse gh pr view output: {e}")
    head_sha = meta.get("headRefOid") or ""
    files = [f["path"] for f in (meta.get("files") or []) if f.get("path")]
    slug = repo or _repo_slug_from_url(meta.get("url", ""))
    return diff, head_sha, files, slug


def _upsert_comment(repo, pr, body):
    """Post one council comment, updating the existing one (matched by MARKER)."""
    marker = "<!-- preflight-council -->"
    existing = _gh(["api", f"repos/{repo}/issues/{pr}/comments", "--paginate",
                    "--jq", f'map(select(.body | contains("{marker}"))) | .[0].id']).strip()
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(body)
        body_path = fh.name
    try:
        if existing and existing != "null":
            _gh(["api", "--method", "PATCH",
                 f"repos/{repo}/issues/comments/{existing}", "-F", f"body=@{body_path}"])
            return "updated"
        _gh(["api", "--method", "POST",
             f"repos/{repo}/issues/{pr}/comments", "-F", f"body=@{body_path}"])
        return "posted"
    finally:
        os.unlink(body_path)


def _load_composer():
    """Import comment/composer.py (lives outside the package) as a module."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "comment", "composer.py")
    spec = importlib.util.spec_from_file_location("preflight_composer", path)
    if spec is None or spec.loader is None:
        raise api.APIError(f"cannot load comment composer at {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def review_command(args):
    """End-to-end: fetch PR -> council -> compose -> print or post. Exit code."""
    if not api.api_key():
        print("set MODULAR_API_KEY", file=sys.stderr)
        return 2

    cfg = config.load(council_yml=args.council_yml, goal=args.goal, cap=args.cap)

    try:
        diff, head_sha, files, repo = _fetch_pr(args.pr, args.repo)
    except api.APIError as e:
        print(f"infrastructure failure: {e}", file=sys.stderr)
        return 2

    diff = config.filter_diff(diff, cfg.paths)
    if not diff.strip():
        print("no diff after path filtering — nothing to review", file=sys.stderr)
        return 0

    where = repo or "PR"
    print(f"{paint('  🚀 PREFLIGHT', 'b', 'cyn')} "
          f"{paint(f'· reviewing {where}#{args.pr} (goal {cfg.goal})…', 'dim')}")

    try:
        result, infra_ok = build_result(
            diff, cfg.goal, cap=cfg.cap, repo_map=build_repo_map())
    except api.APIError as e:
        print(f"infrastructure failure: {e}", file=sys.stderr)
        return 2

    print(render(result))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(result, f, indent=2)
            f.write("\n")

    # Per-character telemetry: append this run to the crew stats ledger.
    try:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        stats.append(result, diff=diff, repo=repo, pr=str(args.pr), ts=ts)
    except OSError:
        pass  # telemetry is best-effort; never fail a review over it

    # Gate BEFORE publishing: never post a comment for a review that failed to
    # parse — a bogus verdict on a real PR is worse than no verdict.
    if not infra_ok:
        print("infrastructure failure: both reviewers unparseable — not posting",
              file=sys.stderr)
        return 2

    body = _load_composer().compose(
        result, art_base=cfg.art_base, repo=repo, sha=head_sha, files=files)

    if args.post:
        try:
            action = _upsert_comment(repo, args.pr, body)
        except api.APIError as e:
            print(f"infrastructure failure: {e}", file=sys.stderr)
            return 2
        print(paint(f"  ✅ council comment {action} on {where}#{args.pr}", "grn"))
    else:
        print(paint("\n  — comment preview (use --post to publish) —", "dim"))
        print(body)

    return 0 if result["verdict"] == "GO" else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="preflight", description="Council PR reviewer on Modular Cloud.")
    sub = parser.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="review a diff (file or stdin)")
    run.add_argument("diff", nargs="?", default="-", help="diff file, or - for stdin")
    run.add_argument("--goal", type=int, default=config.DEFAULT_GOAL,
                     help=f"repo-owner goal score (default {config.DEFAULT_GOAL})")
    run.add_argument("--json", dest="json_out", metavar="OUT", help="also write the frozen JSON contract here")
    run.add_argument("--cap", type=int, default=DEFAULT_CAP, help=argparse.SUPPRESS)

    rev = sub.add_parser("review", help="review a live PR end-to-end (fetch, score, comment)")
    rev.add_argument("pr", help="PR number or URL")
    rev.add_argument("--repo", default=None, help="owner/repo (inferred from cwd or the URL if omitted)")
    rev.add_argument("--goal", type=int, default=None,
                     help=f"override goal (default {config.DEFAULT_GOAL}, or .council.yml)")
    rev.add_argument("--post", action="store_true",
                     help="upsert the council comment on the PR (default: preview only)")
    rev.add_argument("--json", dest="json_out", metavar="OUT", help="also write the frozen JSON contract here")
    rev.add_argument("--council-yml", default=".council.yml", help=argparse.SUPPRESS)
    rev.add_argument("--cap", type=int, default=None, help=argparse.SUPPRESS)

    st = sub.add_parser("stats", help="show lifetime per-crew-member stats from the ledger")
    st.add_argument("--json", dest="json_out", action="store_true", help="emit the aggregate as JSON")

    # Bare invocation without a subcommand behaves like "run" (prototype-friendly).
    if argv and argv[0] not in ("run", "review", "stats", "-h", "--help"):
        argv = ["run"] + argv
    args = parser.parse_args(argv)

    if args.cmd == "review":
        return review_command(args)

    if args.cmd == "stats":
        agg = stats.summarize()
        if args.json_out:
            print(json.dumps(agg, indent=2))
            return 0
        if not agg:
            print("no runs recorded yet — run `preflight review <pr>` first")
            return 0
        print(paint("\n  🛰  COUNCIL CREW — lifetime stats", "b"))
        for key, _emoji, _name in stats.CHARACTERS:
            a = agg.get(key)
            if not a:
                continue
            print(f"\n  {a['emoji']} {paint(a['name'], 'b')}")
            print(f"     PRs reviewed : {a['prs_reviewed']}")
            print(f"     LOC reviewed : {a['loc_reviewed']:,}")
            print(f"     findings     : {a['findings']} ({a['blockers']} blockers)")
            print(f"     avg harshness: {a['avg_harshness']}")
            print(f"     avg note len : {a['avg_issue_len']} chars")
            print(f"     avg time/PR  : {a['avg_ms_per_pr']/1000:.1f}s")
            print(f"     reasoning tok: {a['reasoning_tokens']:,}")
        print("")
        return 0

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
