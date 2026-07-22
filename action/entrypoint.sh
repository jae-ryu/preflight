#!/usr/bin/env bash
# entrypoint.sh — Preflight council CI runner.
#
# 1. fetch the PR diff (gh pr diff, or the GitHub event payload)
# 2. read optional .council.yml in the target repo (goal + path filters)
# 3. run the Preflight CLI -> frozen JSON contract
# 4. compose a delightful markdown comment
# 5. upsert ONE PR comment, idempotent via the hidden marker
#
# Env (set by action.yml, or fake them for a local dry-run):
#   MODULAR_API_KEY   required for the real CLI
#   GH_TOKEN          for gh / gh api
#   GITHUB_REPOSITORY owner/repo
#   GITHUB_EVENT_PATH path to the event JSON (PR number lives here)
#   INPUT_GOAL        default goal
#   INPUT_ART_BASE    optional override for reaction GIF base URL
#   ACTION_PATH / GITHUB_ACTION_PATH  where this action is checked out
#
# Dry-run hooks (for local testing, no real API/network):
#   PREFLIGHT_DIFF_FILE   read the diff from this file instead of gh/event
#   PREFLIGHT_RESULT_JSON use this pre-baked council JSON, skip the CLI
#   PREFLIGHT_SKIP_POST=1 print the comment body instead of posting it
set -euo pipefail

HERE="${GITHUB_ACTION_PATH:-${ACTION_PATH:-$(cd "$(dirname "$0")" && pwd)}}"
REPO_ROOT="$(cd "${HERE}/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

GOAL_DEFAULT="${INPUT_GOAL:-85}"

# ---------- 1. get the raw diff ----------
RAW_DIFF="$WORK/raw.diff"
if [[ -n "${PREFLIGHT_DIFF_FILE:-}" ]]; then
  cp "$PREFLIGHT_DIFF_FILE" "$RAW_DIFF"
else
  PR_NUMBER=""
  if [[ -n "${GITHUB_EVENT_PATH:-}" && -f "${GITHUB_EVENT_PATH}" ]]; then
    PR_NUMBER="$(python3 -c 'import json,os;e=json.load(open(os.environ["GITHUB_EVENT_PATH"]));print(e.get("pull_request",{}).get("number") or e.get("number") or "")')"
  fi
  if [[ -z "$PR_NUMBER" ]]; then
    echo "::error::could not determine PR number from event payload" >&2
    exit 2
  fi
  echo "Fetching diff for PR #$PR_NUMBER" >&2
  gh pr diff "$PR_NUMBER" --repo "${GITHUB_REPOSITORY}" > "$RAW_DIFF"
fi

# Head sha of the PR (for file:line permalinks). Best-effort from the event JSON.
HEAD_SHA=""
if [[ -n "${GITHUB_EVENT_PATH:-}" && -f "${GITHUB_EVENT_PATH}" ]]; then
  HEAD_SHA="$(python3 -c 'import json,os;e=json.load(open(os.environ["GITHUB_EVENT_PATH"]));print(e.get("pull_request",{}).get("head",{}).get("sha") or "")')"
fi
HEAD_SHA="${HEAD_SHA:-${GITHUB_SHA:-}}"

# ---------- 2. .council.yml (goal + path filter) ----------
COUNCIL_YML="${PREFLIGHT_COUNCIL_YML:-.council.yml}"
FILTERED_DIFF="$WORK/filtered.diff"
GOAL_LINE="$(python3 "$HERE/filter_diff.py" "$COUNCIL_YML" "$GOAL_DEFAULT" < "$RAW_DIFF" 2> "$WORK/goal.txt" > "$FILTERED_DIFF"; cat "$WORK/goal.txt")"
GOAL="$(echo "$GOAL_LINE" | sed -n 's/^goal=//p' | tail -1)"
GOAL="${GOAL:-$GOAL_DEFAULT}"
echo "Using goal=$GOAL" >&2

if [[ ! -s "$FILTERED_DIFF" ]]; then
  echo "No diff after filtering — nothing to review." >&2
  exit 0
fi

# ---------- 3. run the council CLI -> frozen JSON ----------
RESULT_JSON="$WORK/result.json"
if [[ -n "${PREFLIGHT_RESULT_JSON:-}" ]]; then
  cp "$PREFLIGHT_RESULT_JSON" "$RESULT_JSON"
  EXIT_CODE=0
else
  set +e
  PYTHONPATH="$REPO_ROOT" python3 -m preflight run "$FILTERED_DIFF" --goal "$GOAL" --json "$RESULT_JSON" > "$WORK/cli.out" 2>&1
  EXIT_CODE=$?
  set -e
  cat "$WORK/cli.out" >&2 || true
  if [[ $EXIT_CODE -eq 2 || ! -s "$RESULT_JSON" ]]; then
    echo "::error::Preflight council infrastructure failure (exit $EXIT_CODE)" >&2
    exit 2
  fi
fi

# ---------- 4. compose the comment ----------
ART_BASE="${INPUT_ART_BASE:-}"
if [[ -z "$ART_BASE" ]]; then
  REF="${GITHUB_SHA:-main}"
  # Reaction GIFs live in this action repo. Resolve raw URL from the action's own repo.
  ACTION_REPO="${GITHUB_ACTION_REPOSITORY:-${GITHUB_REPOSITORY:-jae-ryu/preflight}}"
  ART_BASE="https://raw.githubusercontent.com/${ACTION_REPO}/${GITHUB_ACTION_REF:-main}/art/reactions"
fi
RUN_URL="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID:-}"
COMMENT_MD="$WORK/comment.md"
python3 "$REPO_ROOT/comment/composer.py" "$RESULT_JSON" --art-base "$ART_BASE" \
  --repo "${GITHUB_REPOSITORY:-}" --sha "$HEAD_SHA" --run-url "$RUN_URL" -o "$COMMENT_MD"

# ---------- 4b. persist the run as a build artifact (never committed to the repo) ----------
# Write the frozen JSON + an envelope to the workspace; the workflow uploads it
# with actions/upload-artifact. We NEVER commit run output or open a PR with it.
RUN_ENVELOPE="${GITHUB_WORKSPACE:-$WORK}/preflight-run.json"
TS="$(date -u +%FT%TZ)"
PR="$PR_NUMBER" REPO="${GITHUB_REPOSITORY:-}" HEAD_SHA="$HEAD_SHA" \
RUN_ID="${GITHUB_RUN_ID:-}" TS="$TS" RESULT_JSON="$RESULT_JSON" OUT="$RUN_ENVELOPE" \
python3 - <<'PY'
import json, os
result = json.load(open(os.environ["RESULT_JSON"]))
env = {
    "schema": "preflight/run@2",
    "pr": os.environ.get("PR") or None,
    "repo": os.environ.get("REPO") or None,
    "head_sha": os.environ.get("HEAD_SHA") or None,
    "run_id": os.environ.get("RUN_ID") or None,
    "ts": os.environ.get("TS") or None,
}
env.update(result)
with open(os.environ["OUT"], "w") as f:
    json.dump(env, f, indent=2)
    f.write("\n")
PY
BYTES="$(wc -c < "$RUN_ENVELOPE" | tr -d ' ')"
echo "saved preflight-run.json (${BYTES} bytes) -> artifact preflight-run-pr${PR_NUMBER}" >&2

# ---------- 5. upsert ONE PR comment ----------
if [[ "${PREFLIGHT_SKIP_POST:-}" == "1" ]]; then
  echo "===== PREFLIGHT COMMENT BODY (dry-run, not posted) =====" >&2
  cat "$COMMENT_MD"
  echo "===== END COMMENT BODY =====" >&2
  echo "verdict exit code would be: $EXIT_CODE" >&2
  exit 0
fi

MARKER="<!-- preflight-council -->"
PR_NUMBER="${PR_NUMBER:-$(python3 -c 'import json,os;e=json.load(open(os.environ["GITHUB_EVENT_PATH"]));print(e.get("pull_request",{}).get("number") or e.get("number") or "")')}"

# Find an existing council comment by the hidden marker.
EXISTING_ID="$(gh api "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments" --paginate \
  --jq "map(select(.body | contains(\"$MARKER\"))) | .[0].id" 2>/dev/null || echo "")"

if [[ -n "$EXISTING_ID" && "$EXISTING_ID" != "null" ]]; then
  echo "Updating existing council comment $EXISTING_ID" >&2
  gh api --method PATCH "repos/${GITHUB_REPOSITORY}/issues/comments/${EXISTING_ID}" \
    -F body=@"$COMMENT_MD" >/dev/null
else
  echo "Posting new council comment" >&2
  gh api --method POST "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments" \
    -F body=@"$COMMENT_MD" >/dev/null
fi

exit 0
