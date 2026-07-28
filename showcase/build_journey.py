#!/usr/bin/env python3
"""Build showcase/journey.html — a single, self-contained visual narrative of
the Preflight council: the idea, the tangible code/PR changes, and the impact.

Portraits/reactions are downscaled and base64-embedded so the output is one
portable HTML file (no external assets, opens anywhere). Re-run to regenerate:

    python3 showcase/build_journey.py
"""
from __future__ import annotations

import base64
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ART = os.path.join(REPO, "art")
OUT = os.path.join(HERE, "journey.html")


def data_uri(rel_path: str, box: int = 260, quality: int = 82) -> str:
    """Downscale an art PNG to a small JPEG data URI. Falls back to '' if the
    file or Pillow is missing, so the page still builds (image simply absent)."""
    path = os.path.join(ART, rel_path)
    if not os.path.exists(path):
        return ""
    try:
        from PIL import Image
    except Exception:
        with open(path, "rb") as f:
            raw = base64.b64encode(f.read()).decode()
        return f"data:image/png;base64,{raw}"
    im = Image.open(path).convert("RGB")
    im.thumbnail((box, box), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


CREW = {
    "roaster": data_uri("council-frames/forge_1.png"),
    "mammoth": data_uri("council-frames/mammoth_1.png"),
    "mc": data_uri("council-frames/mc_1.png"),
}


def svg_line(points, w=520, h=170, pad=34, color="#6ee7ff", goal=85,
             ymax=100, labels=None):
    """Tiny dependency-free line chart. `points` = list of (label, value)."""
    n = len(points)
    innerw, innerh = w - 2 * pad, h - 2 * pad

    def x(i):
        return pad + (innerw * i / (n - 1 if n > 1 else 1))

    def y(v):
        return pad + innerh * (1 - v / ymax)

    goal_y = y(goal)
    poly = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(points))
    dots, xlabels, vlabels = [], [], []
    for i, (lab, v) in enumerate(points):
        cx, cy = x(i), y(v)
        dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="{color}"/>')
        vlabels.append(
            f'<text x="{cx:.1f}" y="{cy - 11:.1f}" fill="#e8eefc" '
            f'font-size="12.5" font-weight="700" text-anchor="middle">{v}</text>'
        )
        xlabels.append(
            f'<text x="{cx:.1f}" y="{h - 10:.1f}" fill="#8aa0c6" '
            f'font-size="10.5" text-anchor="middle">{lab}</text>'
        )
    return f"""<svg viewBox="0 0 {w} {h}" width="100%" role="img">
  <line x1="{pad}" y1="{goal_y:.1f}" x2="{w - pad}" y2="{goal_y:.1f}"
        stroke="#3b4d6b" stroke-dasharray="5 5"/>
  <text x="{w - pad}" y="{goal_y - 6:.1f}" fill="#8aa0c6" font-size="10.5"
        text-anchor="end">goal {goal}</text>
  <polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2.5"
        stroke-linejoin="round"/>
  {''.join(dots)}{''.join(vlabels)}{''.join(xlabels)}
</svg>"""


REPORT_V4 = svg_line(
    [("c1", 59), ("c2", 83), ("c3", 59)], color="#c084fc")
PR92708 = svg_line(
    [("manual", 44), ("A", 43), ("+fixes", 59), ("cold", 51), ("hardened", 71)],
    color="#6ee7ff")


HTML = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Preflight — bringing the council home</title>
<style>
  :root {{
    --bg:#0a0e1a; --panel:#121a2e; --panel2:#0f1626; --ink:#e8eefc;
    --dim:#8aa0c6; --line:#233350; --cyan:#6ee7ff; --violet:#c084fc;
    --green:#5ee39b; --amber:#ffcf6e; --red:#ff8a8a;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:radial-gradient(1200px 700px at 70% -10%, #16233f 0%, var(--bg) 55%);
    color:var(--ink); font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif; }}
  a {{ color:var(--cyan); }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:44px 22px 80px; }}
  .kicker {{ letter-spacing:.22em; text-transform:uppercase; font-size:11.5px; color:var(--cyan); font-weight:700; }}
  h1 {{ font-size:40px; line-height:1.1; margin:10px 0 8px; letter-spacing:-.5px; }}
  h1 .g {{ background:linear-gradient(90deg,var(--cyan),var(--violet)); -webkit-background-clip:text; background-clip:text; color:transparent; }}
  .lede {{ color:var(--dim); font-size:17px; max-width:760px; }}
  section {{ margin-top:40px; }}
  h2 {{ font-size:13px; letter-spacing:.16em; text-transform:uppercase; color:var(--dim); border-bottom:1px solid var(--line); padding-bottom:8px; }}
  .crew {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:18px; }}
  .card {{ background:linear-gradient(180deg,var(--panel),var(--panel2)); border:1px solid var(--line); border-radius:16px; padding:16px; }}
  .crew .card {{ text-align:center; }}
  .crew img {{ width:100%; border-radius:12px; aspect-ratio:1/1; object-fit:cover; border:1px solid var(--line); }}
  .crew h3 {{ margin:12px 0 2px; font-size:16px; }}
  .crew .role {{ color:var(--dim); font-size:12.5px; min-height:34px; }}
  .crew .model {{ margin-top:8px; font:11.5px ui-monospace,Menlo,monospace; color:var(--amber); }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .grid3 {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }}
  @media (max-width:820px) {{ .grid2,.grid3,.crew {{ grid-template-columns:1fr; }} h1{{font-size:32px;}} }}
  .stat {{ text-align:center; }}
  .stat .n {{ font-size:30px; font-weight:800; letter-spacing:-1px; }}
  .stat .l {{ color:var(--dim); font-size:12px; margin-top:2px; }}
  code, pre {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
  pre {{ background:#0b1120; border:1px solid var(--line); border-radius:12px; padding:14px 16px; overflow:auto; font-size:12.5px; margin:0; }}
  pre .del {{ color:var(--red); }} pre .add {{ color:var(--green); }} pre .cm {{ color:#5f7194; }}
  .pill {{ display:inline-block; font-size:11px; padding:2px 9px; border-radius:999px; border:1px solid var(--line); color:var(--dim); }}
  .pill.go {{ color:var(--green); border-color:#255e43; background:#0e2519; }}
  .pill.hold {{ color:var(--amber); border-color:#5e4c1f; background:#241d0c; }}
  .pill.block {{ color:var(--red); border-color:#5e2727; background:#240f0f; }}
  .tl {{ position:relative; margin-top:18px; padding-left:26px; }}
  .tl::before {{ content:""; position:absolute; left:8px; top:6px; bottom:6px; width:2px; background:var(--line); }}
  .ev {{ position:relative; margin-bottom:16px; }}
  .ev::before {{ content:""; position:absolute; left:-22px; top:5px; width:11px; height:11px; border-radius:50%; background:var(--cyan); box-shadow:0 0 0 3px #0a0e1a; }}
  .ev.done::before {{ background:var(--green); }} .ev.wait::before {{ background:var(--amber); }} .ev.block::before {{ background:var(--red); }}
  .ev h4 {{ margin:0 0 2px; font-size:15px; }}
  .ev p {{ margin:0; color:var(--dim); font-size:13.5px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--dim); font-weight:600; font-size:11.5px; text-transform:uppercase; letter-spacing:.08em; }}
  .mono {{ font-family:ui-monospace,Menlo,monospace; }}
  .note {{ color:var(--dim); font-size:12.5px; margin-top:8px; }}
  .cap {{ color:var(--dim); font-size:12px; margin-top:8px; text-align:center; }}
  .foot {{ margin-top:54px; color:#5f7194; font-size:12px; border-top:1px solid var(--line); padding-top:18px; }}
  .hl {{ color:var(--ink); }}
</style></head>
<body><div class="wrap">

  <div class="kicker">Preflight · a system that reviews itself</div>
  <h1>Bringing the <span class="g">council</span> home</h1>
  <p class="lede">An LLM PR-review <b>council</b> that runs on Modular Cloud, gates real pull requests,
  and — the whole point — <b>measures and improves its own judgment</b>. This is the tangible trail:
  the crew, the code, the scores, and what's still cooking.</p>

  <section>
    <h2>The crew · three lanes, one gate</h2>
    <div class="crew">
      <div class="card">
        <img src="{CREW['roaster']}" alt="Roaster">
        <h3>🔥 Roaster</h3>
        <div class="role">Bugs &amp; correctness — logic errors, crashes, races, unhandled failures, leaks, security. Roasts the flaw, not the person.</div>
        <div class="model">moonshotai/Kimi-K2.6</div>
      </div>
      <div class="card">
        <img src="{CREW['mammoth']}" alt="Mammoth">
        <h3>🦣 Mammoth</h3>
        <div class="role">Fine-tooth comb — architecture, API/contract design, naming, missing tests, docs, maintainability. Calm, precise.</div>
        <div class="model">moonshotai/Kimi-K2.6</div>
      </div>
      <div class="card">
        <img src="{CREW['mc']}" alt="Mission Control">
        <h3>🧑‍🚀 Mission Control</h3>
        <div class="role">Overseer — synthesizes the verdict against a repo-owner goal. Deterministic zero-blocker gate: any blocker ⇒ HOLD.</div>
        <div class="model">google/gemma-4-31B-it</div>
      </div>
    </div>
    <p class="note">Every PR (open / sync / reopen) gets <b>one</b> auto-upserted comment: a score out of 100,
    a per-grader × per-dimension breakout, blockers as GitHub suggested-changes, and a collapsed run-trace.
    The score is advisory; the <b>zero-blocker rule</b> is the hard gate.</p>
  </section>

  <section>
    <h2>The idea · deterministic gate, LLM eyes</h2>
    <div class="grid3">
      <div class="card"><div class="stat"><div class="n" style="color:var(--cyan)">100→</div><div class="l">rubric starts at 100, subtracts by severity (−12 blocker / capped nits); model may nudge ±5</div></div></div>
      <div class="card"><div class="stat"><div class="n" style="color:var(--violet)">map⇄reduce</div><div class="l">diffs &gt;24k split into ≤6 parallel chunks; findings merged &amp; de-duped in code, not by the model</div></div></div>
      <div class="card"><div class="stat"><div class="n" style="color:var(--green)">GO / HOLD</div><div class="l">GO iff zero blockers — the verdict never depends on a noisy number</div></div></div>
    </div>
  </section>

  <section>
    <h2>The tangible · what actually shipped</h2>
    <table>
      <tr><th>Axis</th><th>Where</th><th>Meaning</th><th>Now</th></tr>
      <tr><td>Product</td><td class="mono">__version__</td><td>the tool as a whole (pre-1.0 SemVer)</td><td class="mono hl">0.4.0</td></tr>
      <tr><td>Run contract</td><td class="mono">CONTRACT_VERSION</td><td>the run@N stored-JSON shape</td><td class="mono hl">3</td></tr>
      <tr><td>Rubric</td><td class="mono">RUBRIC_VERSION</td><td>the scoring math only</td><td class="mono hl">1</td></tr>
    </table>
    <div class="grid2" style="margin-top:16px">
      <div class="card">
        <h4 style="margin:0 0 6px">🟣 PR #7 · <span class="mono">feat/report-v4</span> <span class="pill go">MERGED</span></h4>
        <p class="note" style="margin-top:0">Per-grader / per-dimension score breakout, the anti-slop report composer
        (suggested-change blocks + collapsed nits), run@3 stats ledger, rubric versioning, evidence &amp; size-gate behaviors.</p>
      </div>
      <div class="card">
        <h4 style="margin:0 0 6px">🔵 PR #8 · <span class="mono">feat/trust-loop</span> <span class="pill hold">OPEN · council-green</span></h4>
        <p class="note" style="margin-top:0">The honest self-improvement scope stacked on #7:
        <span class="mono">feedback.py</span> (signal ratio), <span class="mono">anchor.py</span> (dual-score across rubric versions),
        <span class="mono">loop_guard.py</span> (stop-rules), and the self-improve skill.</p>
      </div>
    </div>
  </section>

  <section>
    <h2>Today · the council caught real bugs in the code that measures the council</h2>
    <p class="lede" style="font-size:15px">Run&nbsp;1 on #8 → <span class="pill hold">HOLD 71/100</span>, 2 blockers.
    Both were real, and both lived in <span class="mono">feedback.py</span> — the module whose entire job is to
    honestly measure trust. The system critiqued itself. We fixed it.</p>
    <div class="grid2" style="margin-top:14px">
      <div class="card">
        <div class="pill block">Blocker 1 · trust_metrics</div>
        <p class="note">"Safe wrapper that isn't safe" — the docstring promised never-raises, but a bad ledger read fell straight through.</p>
<pre><span class="cm"># before — read_rows() could raise straight through</span>
feedback = load(feedback_path)
ledger_rows = stats.read_rows(ledger_path)

<span class="cm"># after — degrade ANY failure to "no data", never crash</span>
<span class="add">feedback = _safe(load, feedback_path, default=[])</span>
<span class="add">ledger_rows = _safe(stats.read_rows, ledger_path, default=[])</span></pre>
      </div>
      <div class="card">
        <div class="pill block">Blocker 2 · stats CLI</div>
        <p class="note">One bad feedback file crashed the whole <span class="mono">stats</span> command before it could print anything.</p>
<pre><span class="cm"># after — the stats command survives a degraded trust surface</span>
<span class="add">try:</span>
<span class="add">    trust = feedback.trust_metrics()</span>
<span class="add">except Exception:</span>
<span class="add">    trust = {{}}</span></pre>
        <p class="note">+ hardened <span class="mono">read_rows</span> (OSError/UTF-8), non-list <span class="mono">findings_detail</span> guard,
        and 4 new regression tests. <b>220 tests green.</b></p>
      </div>
    </div>
  </section>

  <section>
    <h2>The evidence · why "did it score higher?" is the wrong question</h2>
    <div class="grid2">
      <div class="card">
        <h4 style="margin:0 0 4px">Same code, three runs — score is not monotonic</h4>
        {REPORT_V4}
        <p class="cap">report-v4 dogfooded on its own PR across 3 commits — fresh real blockers each round.</p>
      </div>
      <div class="card">
        <h4 style="margin:0 0 4px">#92708 — the climb as real bugs got fixed</h4>
        {PR92708}
        <p class="cap">BOS MCP server PR: each rise followed a genuine fix, not a nicer prompt.</p>
      </div>
    </div>
    <div class="grid3" style="margin-top:16px">
      <div class="card"><div class="stat"><div class="n" style="color:var(--red)">±47</div><div class="l">points of pure LLM sampling noise measured on <i>identical</i> code — a single score can't be trusted</div></div></div>
      <div class="card"><div class="stat"><div class="n" style="color:var(--green)">signal ratio</div><div class="l">the rubric-invariant north star: findings <i>acted-on</i> ÷ findings with a verdict. A rubric change can't move it — only being useful can</div></div></div>
      <div class="card"><div class="stat"><div class="n" style="color:var(--cyan)">Δreal = Δscore − Δrubric</div><div class="l">dual-score a frozen anchor set across rubric versions, so real improvement is separated from a moved goalpost</div></div></div>
    </div>
    <p class="note">The honest metric isn't "the number went up." It's <b>new true-positive finding-classes caught per charter version</b>
    (monotonic) and the <b>score distribution over N runs at a fixed rubric</b>. That's data-science / ML-eval territory — holdout sets,
    anchor scoring, drift detection — and the trust-loop leans into it on purpose.</p>
  </section>

  <section>
    <h2>Where it stands · and what we keep iterating on</h2>
    <div class="tl">
      <div class="ev done"><h4>#7 report-v4 — merged</h4><p>Per-dimension breakout + anti-slop report live on <span class="mono">main</span>.</p></div>
      <div class="ev done"><h4>#8 blockers fixed &amp; pushed <span class="mono">(c3ba3d1)</span></h4><p>trust surface is now genuinely crash-proof; 220 tests green.</p></div>
      <div class="ev wait"><h4>Council re-run ≥2× — pending infra</h4><p>Modular Cloud inference was returning <span class="mono">404</span> on every model when we pushed — the re-run fires automatically the moment MCloud recovers. (The tool depends on the very cloud it reviews for: on-thesis.)</p></div>
      <div class="ev done"><h4>#92708 — ready for review, CI-green</h4><p>Draft flag cleared; both Buildkite checks pass. Now awaiting human CODEOWNERS approval — the gate we deliberately don't bypass.</p></div>
      <div class="ev wait"><h4>Warehouse the loop — ready, not yet wired</h4><p>run@3 emits everything a warehouse needs (grader, per-finding dim/tag/sev/tier, <span class="mono">rubric_version</span>) — but the BigQuery bridge itself is still open work (FIN-711). Emit ✔, ingest ✘.</p></div>
    </div>
  </section>

  <div class="foot">
    Preflight · Kimi&nbsp;K2.6 + Gemma&nbsp;4 on Modular&nbsp;Cloud &nbsp;·&nbsp;
    <a href="https://github.com/jae-ryu/preflight/pull/8">#8 feat/trust-loop</a> &nbsp;·&nbsp;
    <a href="https://github.com/jae-ryu/preflight/pull/7">#7 feat/report-v4</a> &nbsp;·&nbsp;
    <a href="https://github.com/modularml/modular/pull/92708">modular#92708</a><br>
    Generated by <span class="mono">showcase/build_journey.py</span> — self-contained, no external assets.
  </div>

</div></body></html>"""


def main() -> None:
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(HTML)
    print(f"wrote {OUT}  ({len(HTML):,} bytes)")


if __name__ == "__main__":
    main()
