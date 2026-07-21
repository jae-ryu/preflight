# 🚀 PREFLIGHT

A **council** PR reviewer that dogfoods [Modular Cloud](https://api.modular.com) (MCloud).
Three characters read a diff, argue, and call **GO / HOLD** against a repo-owner goal score.

## The crew

| | Character | Model | Beat |
|---|---|---|---|
| 🔥 | **ROASTER** | `moonshotai/Kimi-K2.6` | Bugs & correctness — logic errors, crashes, races, unhandled failures, leaks, security. Punchy, roasts the flaw not the person, ends useful. |
| 🦣 | **MAMMOTH** | `moonshotai/Kimi-K2.6` | Fine-tooth comb — architecture, API/contract design, naming, **missing tests**, docs, consistency. Calm, precise. |
| 🧑‍🚀 | **MISSION CONTROL** | `google/gemma-4-31B-it` | Overseer — weighs both reports, scores, calls the launch. Caveman-brief exec summary. |

Kimi K2.6 is a *reasoning* model: its response carries both `content` and
`reasoning_content` and spends ~6-8k tokens thinking before it answers. Preflight
budgets `max_tokens=20000` and parses defensively — `content` first, then JSON out of
`reasoning_content`, then one repair-retry that asks the model to re-emit ONLY the JSON.

## Triage & scoring rubric (v2)

Every finding is deterministically tiered **in code** — reviewers do not choose the tier:

- **🚧 blocker** = any **high-severity** finding, from either reviewer.
- **🧹 nit** = any **medium / low** finding.

The JSON carries top-level **`blockers`** and **`nits`** counts.

Start at **100**. Deduct:

- blocker **correctness** (ROASTER high) — **−12** each
- blocker **design/tests** (MAMMOTH high) — **−8** each
- nit **medium** — **−3** each
- nit **low** — **−1** each
- the **total nit deduction is capped at −10** — a pile of small stuff can't sink a PR

Floor 0. The overseer may nudge the score for holistic judgment, but the code
**clamps the model score to the deterministic rubric ±5**. Verdict is **GO** only if
the final score ≥ goal **AND** there are **zero blockers** — that gate is enforced in
`rubric.py` regardless of what the model said.

Reviewers are prompted for **at most 3 gating problems + 5 nits**, quality over volume —
the product principle is *don't spam the PR*.

## Usage

```bash
export MODULAR_API_KEY=sk-mod-...

# review a diff file, repo owner sets the bar
python -m preflight run change.diff --goal 85

# review from stdin
git diff main... | python -m preflight run - --goal 85

# also emit the machine-readable contract
python -m preflight run change.diff --goal 85 --json out.json
```

Exit codes: **0** = GO, **1** = HOLD, **2** = infrastructure failure (API down or both
reviewers unparseable).

### JSON contract (frozen, v2)

```json
{
  "version": 2,
  "goal": 85,
  "score": 62,
  "verdict": "HOLD",
  "blockers": 2,
  "nits": 4,
  "summary": "<MC exec summary, <=20 words>",
  "top_actions": ["...", "...", "..."],
  "reviewers": {
    "roaster": {"summary": "...", "findings": [{"sev":"high|med|low","tier":"blocker|nit","where":"file:line","issue":"...","say":"in-character quote"}], "parse_ok": true},
    "mammoth": {"summary": "...", "findings": [...], "parse_ok": true}
  },
  "meta": {"models": {"reviewers":"moonshotai/Kimi-K2.6","overseer":"google/gemma-4-31B-it"}, "diff_bytes": 111888, "truncated": false, "chunks": 6, "skipped_files": []}
}
```

`tier` is stamped deterministically in code. `blockers`/`nits` are the counts across
both reviewers. `meta.chunks` is how many map-reduce chunks were reviewed (1 = single
pass); `meta.skipped_files` lists any files dropped when a diff exceeds the chunk budget.

## Diff handling — single-pass and map-reduce

- **Diff ≤ 24000 chars** → single pass, exactly one review per reviewer.
- **Diff > 24000 chars** → **per-file map-reduce**. The diff is split on file
  boundaries (`diff --git`) and packed into chunks of **≤ 20000 chars** (tiny files
  grouped together), capped at **6 chunks**. Beyond that, the largest / most-changed
  files keep their slots and the rest are recorded in `meta.skipped_files`. Each
  reviewer reviews every chunk **in parallel**, then a cheap **code-side merge**
  concatenates findings, dedupes near-identical `where` (keeping the highest
  severity), re-sorts by severity, and applies the **3 gating + 5 nit** caps per
  reviewer. Per-chunk summaries are compressed into one line by a light-model call.

`meta.truncated` remains for the legacy single-pass cap case; `meta.chunks` reflects
the map-reduce fan-out.

## Layout

```
preflight/
  preflight/
    api.py       # MCloud HTTP + retries + robust JSON extraction / repair-retry
    crew.py      # personas, prompts, reviewer + overseer orchestration
    rubric.py    # deterministic tiering + scoring, ±5 clamp, blocker gating
    diffcap.py   # smart file/hunk-boundary truncation (single-pass cap)
    chunk.py     # per-file map-reduce splitting for big diffs
    cli.py       # terminal render + --json, exit codes
  tests/         # pytest, API fully mocked
  runs/          # saved live-run outputs
```

## Development

```bash
python -m pytest -q
```

## Add Preflight to your repo in 2 minutes

Opt in for a whole repo with **one file + one secret** — no app, no server, no config service.

1. **Copy the workflow.** Drop [`action/examples/preflight.yml`](action/examples/preflight.yml)
   into your repo at `.github/workflows/preflight.yml`.

2. **Add the secret.** In your repo, go to *Settings → Secrets and variables → Actions*
   and add a secret named **`MODULAR_API_KEY`** with your Modular Cloud key.

That's it. Every pull request now gets **one** council comment (opened, updated in
place on each push via the hidden `<!-- preflight-council -->` marker) with a GO / HOLD
verdict, a score bar, the crew's best one-liners, a top-actions checklist, a
collapsible findings table, and a character reaction GIF.

### Optional: `.council.yml`

Drop a `.council.yml` at your repo root to tune the review:

```yaml
goal: 90              # the bar a PR must clear to get GO (default 85)
paths:                # only review diff files under these paths / globs
  - "src/"
  - "*.py"
```

- **`goal`** — score threshold. GO requires `score >= goal` **and** zero blockers
  (any high-severity finding, either reviewer).
- **`paths`** — filters which changed files the council looks at. Omit to review the
  whole diff.

### How reaction GIFs resolve

The comment embeds a reaction GIF (`go-triumphant` / `hold-close` / `hold-rough`)
from `art/reactions/`. Since GitHub PR comments need an image **URL**, the action
serves them from the raw URL of the Preflight action repo
(`https://raw.githubusercontent.com/<owner>/preflight/<ref>/art/reactions/…`).
That repo must be public for the images to render. Override the base with the
action's `art_base` input if you host the GIFs elsewhere.

### Exit codes

The council CLI exits `0` on GO, `1` on HOLD, `2` on infrastructure failure — so you
can make the check blocking (fail the PR on HOLD) or advisory (comment only) as you like.

## Roadmap

The CI action is the **v1 delivery vehicle** — the fastest way to get the council in
front of a diff with one file and one secret. Next:

- **Future: a long-running service in the monorepo.** A CloudInfra webapp/service
  running on MCloud endpoints, listening for review requests (webhooks / a review
  queue) rather than spinning up a fresh runner per PR — shared caching, richer
  cross-PR context, and central rubric/policy config. The GitHub Action stays as the
  zero-infra on-ramp; the service becomes the scaled path.

---
🚀 Preflight council · powered by Modular Cloud (Kimi K2.6 + Gemma 4 + FLUX.2)
