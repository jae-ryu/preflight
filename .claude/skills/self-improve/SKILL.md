---
name: self-improve
description: Run a system that improves itself, honestly. Freeze a holdout, score, propose changes, fan out to apply each in isolation, adversarially verify, measure the REAL gain (netting out any ruler change) on the frozen holdout, then graduate or revert under hard stop-rules. Generalizes beyond PR review to docs, migrations, and test-gen. Invoke with "/self-improve <target>" or "improve X against a holdout".
argument-hint: <what to improve, e.g. the PR-review rubric | a docs set | a migration | a test suite> [holdout manifest]
---

# self-improve — the honest self-improvement loop

You run a target through iterated self-improvement **without lying to yourself**.
The trap every self-tuning system falls into is scoring itself with the same
ruler it is changing, then celebrating a number that only moved because the ruler
moved. This loop makes improvement *measurable and safe*: gains must generalize
to a frozen set the changes never touched, and hard stop-rules halt the loop
before it overfits, cycles, or graduates noise into policy.

Sibling to `cook` (runs a service of swarm work) and `route` (picks a tier). This
one is the meta-loop that makes any such system get genuinely better over time.

## The invariants (do not skip these — they are the whole point)

1. **Freeze a holdout FIRST.** Before any change, pin a frozen set the loop is
   forbidden to edit — the generalization set. In Preflight this is the anchor
   manifest (`config.holdout`, scored by `preflight/anchor.py`). For docs it's a
   held-out page set; for migrations, a held-out schema/fixture pair; for
   test-gen, a held-out module. The holdout's INPUT never changes, so any score
   move on it is real.
2. **Signal over score.** Prefer a rubric-invariant, ground-truth metric as the
   north star (Preflight: SIGNAL RATIO = findings acted-on ÷ findings with a
   determined outcome, `preflight/feedback.py`). A raw self-score is a proxy;
   trust it only as far as the holdout and ground truth agree.
3. **Net out the ruler.** If you change the scorer/rubric itself, re-score the
   frozen holdout under BOTH versions and compute Δrubric (the offset with input
   held constant). Then **Δreal = Δscore − Δrubric** (`anchor.delta_real`). Only
   Δreal counts as improvement. A rubric bump is a labelled discontinuity on the
   trend, never averaged through.

## The loop

```
freeze holdout
  → evaluate baseline (any scorer) on target + holdout; record signal + scores
  → propose changes (each a small, described, reversible diff)
  → FAN OUT: apply each candidate in isolation (own branch/worktree)   [cook-style]
  → adversarial-verify each (tests, a fresh cold-eyes reviewer, the guards)
  → measure Δreal on the HOLDOUT (net out Δrubric)
  → graduate the winners | revert the rest
  → check stop-rules → loop or halt
```

- **Fan-out-apply in isolation** so candidates never contaminate each other; each
  is judged alone against the same frozen holdout. Route the mechanical apply
  down-tier (see `route`); keep proposal + final judgment high-tier.
- **Adversarial verify** means a *different* evaluator than the one that proposed
  the change confirms the gain — never let the author grade its own homework.

## Stop-rules (pure decisions — obey them; in Preflight, `preflight/loop_guard.py`)

- **Iteration cap** — never coach→rerun a single target forever
  (`iteration_cap_reached`, default 3).
- **Overfitting detector** — halt when the coached self-score climbs but the
  holdout stays flat; the coached↔holdout gap exceeding tolerance while the
  holdout did not gain means you are tuning to the case in front of you, not
  improving (`is_overfitting`).
- **Cycle detection** — reject a change that reverts a change already applied
  (A→B then B→A); otherwise the loop oscillates forever (`is_cycle`).
- **Graduation gate** — a recurring pattern enters the permanent charter/policy
  only when it recurs **confirmed-real** (acted-on ground truth), never on raw
  recurrence. Noise that repeats is still noise (`can_graduate`).

## Generalizing the target

| Domain | Target | Holdout | Scorer | Ground-truth signal |
|---|---|---|---|---|
| PR review | rubric / prompts | frozen past runs (anchor set) | `rubric.rubric_score` | findings acted-on (signal ratio) |
| Docs | style/structure rules | held-out page set | readability/lint scorer | reader edits / "was this helpful" |
| Migrations | transform rules | held-out schema+fixtures | round-trip correctness | prod rows migrated clean |
| Test-gen | generation prompt | held-out modules | coverage + mutation score | bugs the tests actually catch |

The mechanism is identical; only the scorer and the ground-truth signal swap.
If you cannot name a frozen holdout AND a ground-truth signal for the target,
you are not ready to run this loop — stop and define them first.

## Output

Report, every pass: baseline vs current signal ratio; Δscore, Δrubric, and the
**Δreal** on the holdout; which candidates graduated vs reverted and why; and
which stop-rule (if any) halted the loop. A pass that moved the self-score but
not Δreal is a **no-op you must report as such** — not a win.
