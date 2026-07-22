# Council crew stats — "how the crew works"

The council **charter** ([artifact](https://claude.ai/code/artifact/a6adc232-9a1a-4562-9895-f734165b22b9))
says what each crew member is *chartered* to do. This is its sibling: it tracks
how they **actually** work, run over run, so we can analyze the crew later.

## Where the log is persisted

Every `preflight review <pr>` appends **one row per crew member per run** to:

```
runs/reviewer-stats.jsonl          # append-only JSONL, one row per character per run
```

(`preflight/stats.py::DEFAULT_LEDGER`.) Append-only JSONL keeps it trivially
greppable and warehouse-ingestable — this is the local staging file for the
`preflight/run@2` → warehouse ingest (Linear **FIN-711**, tied to **FIN-629**
review-check telemetry). The future `preflight.modular.com` PR console
(**FIN-709**) reads these to render the "how they work" view.

## What we track per character (🔥 Roaster · 🦣 Mammoth · 🧑‍🚀 Mission Control)

Per run row:
- `findings`, `blockers`, `nits`, `suggestions`
- `avg_issue_len` — average note length (chars)
- `harshness` — reviewers: severity-weighted finding volume; MC: normalized goal gap
- `blocker_ratio`
- `duration_ms` — summed across chunk + repair nodes for that character (speed)
- `tokens.completion` / `tokens.reasoning` — how much thinking each burns
- run context: `repo`, `pr`, `head_sha`, `goal`, `score`, `verdict`, `diff.{bytes,changed_files,added,removed}` (LOC)

Aggregate (lifetime) view, via `preflight stats` (or `stats.summarize()`):
- **PRs reviewed** so far
- **LOC reviewed**
- total findings / blockers
- **avg harshness**, **avg note length**
- **avg time per PR**, total reasoning tokens

## Ideas not yet captured (backlog)

- speed-to-PR (wall time from PR open → council verdict) — needs PR `created_at`
- agreement rate between 🔥 and 🦣 (cross-flag overlap already computed at dedupe)
- harshness drift over time / per repo
- false-positive rate (findings later dismissed by the author)
