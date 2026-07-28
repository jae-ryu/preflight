# Changelog

Preflight is **pre-1.0**: the product version is `0.MINOR.PATCH`, and each
significant iteration is a MINOR bump while behavior is still allowed to move.
We do NOT jump whole major versions (the earlier `2.x`/`3.x` labels were a
mistake — those were informal "report v2/v4" nicknames, not releases).

Three version axes are tracked independently — see `preflight/__init__.py`:

| Axis | Where | Meaning | Now |
|---|---|---|---|
| Product | `__version__` | the tool as a whole (SemVer, pre-1.0) | `0.4.0` |
| Run contract | `CONTRACT_VERSION` | the run@N stored-JSON shape | `3` |
| Rubric | `rubric.RUBRIC_VERSION` | the scoring math only | `1` |

## 0.4.0 — Trust loop + honest self-improvement (PR #8)
- `feedback.py`: ground-truth capture (acted-on / dismissed / CI-passed / merged)
  and **signal ratio** (findings acted-on ÷ total) — the rubric-invariant north star.
- `anchor.py`: dual-score a frozen anchor set across rubric versions to isolate
  `Δrubric`, so `Δreal = Δscore − Δrubric` is measurable.
- `loop_guard.py`: honest-loop stop rules (iteration cap, overfitting/holdout-gap
  detector, cycle detection, graduate-only-on-confirmed-real).
- `.claude/skills/self-improve/`: the self-improvement loop codified as a reusable
  swarming pattern (freeze → evaluate → propose → fan-out-apply → adversarial-verify
  → measure Δreal → graduate | revert → stop-rule).

## 0.3.0 — Dimension breakout, tune-up behaviors, rubric versioning (PR #7)
- Contract v3: every finding attributed to a grader **lane dimension**; per-dimension
  → per-grader scores (`grader_scores`, `dimension_scores`).
- Report composer: verdict + score-breakout table + blockers as GitHub
  suggested-changes + collapsed nits (replaced the wall-of-text comment).
- Tune-up-report behaviors (research → AI-native): **R1** evidence rule (no proof,
  no blocker), **R2** ~400-LOC size gate (advisory), **R3** Mammoth `design` lens
  (non-gating questions) + Code Atlas dependency-graph grounding seam.
- `RUBRIC_VERSION` introduced; run@3 stats ledger + additive BigQuery mapping
  (`preflight.dimension` / `preflight.finding` rows carrying failure-class tags).

## 0.2.0 — Council craft
- Cross-reviewer dedupe (deduct once), exact score deltas on re-runs, resolved
  permalinks, sharpened lanes, run-trace DAG, severity anchors, failure-path +
  error-handling coaching baked into the charter.

## 0.1.0 — First flight
- Three-persona council (🔥 Roaster / 🦣 Mammoth / 🧑‍🚀 Mission Control) on Modular
  Cloud, deterministic rubric ("model proposes, rubric disposes"), GO/HOLD gate,
  GitHub Action opt-in, single upserted PR comment.
