"""Local-runtime support: per-character models and inline <think> stripping.

These cover the two ways a local council differs from the hosted one. Both are
silent-wrong failures rather than loud ones, which is why they get their own
tests: a shared reviewer model looks like agreement, and a draft object parsed
out of a think block looks like a successful review.
"""

import pytest

from preflight import api, models


# ── per-character model resolution ──────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "PREFLIGHT_ROASTER_MODEL", "PREFLIGHT_MAMMOTH_MODEL", "PREFLIGHT_MC_MODEL",
        "PREFLIGHT_REVIEWER_MODEL", "PREFLIGHT_OVERSEER_MODEL",
        "PREFLIGHT_REASONING_MODEL", "PREFLIGHT_FAST_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_characters_fall_back_to_task_models_when_unset():
    """Hosted behaviour must be unchanged: no per-character env, no new split."""
    assert models.model_for_character("roaster") == models.reviewer_model()
    assert models.model_for_character("mammoth") == models.reviewer_model()
    assert models.model_for_character("mc") == models.overseer_model()


def test_each_character_can_run_a_distinct_model(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_ROASTER_MODEL", "devstral-2:22b")
    monkeypatch.setenv("PREFLIGHT_MAMMOTH_MODEL", "gpt-oss:20b")
    monkeypatch.setenv("PREFLIGHT_MC_MODEL", "qwen2.5-coder:7b")

    picked = {c: models.model_for_character(c) for c in ("roaster", "mammoth", "mc")}
    assert picked == {
        "roaster": "devstral-2:22b",
        "mammoth": "gpt-oss:20b",
        "mc": "qwen2.5-coder:7b",
    }
    # The point of the feature: no two reviewers on the same weights.
    assert len(set(picked.values())) == 3


def test_character_override_beats_task_model(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_REVIEWER_MODEL", "task-level")
    monkeypatch.setenv("PREFLIGHT_ROASTER_MODEL", "character-level")
    assert models.model_for_character("roaster") == "character-level"
    # Mammoth, with no override of its own, still follows the task model.
    assert models.model_for_character("mammoth") == "task-level"


def test_api_resolves_per_call_not_at_import(monkeypatch):
    """Env set after import must still take effect — the CLI configures late."""
    monkeypatch.setenv("PREFLIGHT_ROASTER_MODEL", "set-after-import")
    assert api.model_for_character("roaster") == "set-after-import"


# ── inline chain-of-thought stripping ───────────────────────────────────────

def test_strip_think_removes_block():
    assert api.strip_think("<think>pondering</think>{\"a\": 1}") == '{"a": 1}'


@pytest.mark.parametrize("tag", ["think", "thinking", "reasoning", "THINK"])
def test_strip_think_handles_tag_variants(tag):
    text = f"<{tag}>noise</{tag}>{{\"ok\": true}}"
    assert api.strip_think(text) == '{"ok": true}'


def test_strip_think_drops_unterminated_block():
    """Truncated mid-thought is the normal shape when max_tokens runs out."""
    assert api.strip_think('{"real": 1}\n<think>cut off here') == '{"real": 1}'


def test_strip_think_is_a_noop_for_hosted_responses():
    """MCloud puts thinking in reasoning_content, so content is already clean."""
    clean = '{"summary": "fine", "findings": []}'
    assert api.strip_think(clean) == clean


def test_strip_think_tolerates_empty():
    assert api.strip_think("") == ""
    assert api.strip_think(None) is None


def test_draft_json_inside_think_is_not_mistaken_for_the_answer():
    """The failure this exists to prevent.

    extract_json returns the FIRST balanced object. A local model that drafts
    its JSON while reasoning would otherwise have the draft accepted as the
    real review — wrong findings, wrong severities, and parse_ok True.
    """
    reply = (
        '<think>Maybe I should say {"summary": "draft", '
        '"findings": [{"sev": "high", "issue": "WRONG"}]} — no, let me reconsider.'
        "</think>\n"
        '{"summary": "final", "findings": []}'
    )
    assert api.extract_json(reply)["summary"] == "draft"        # the bug
    assert api.extract_json(api.strip_think(reply))["summary"] == "final"  # the fix


def test_multiple_think_blocks_all_removed():
    reply = '<think>one</think>noise<think>two</think>{"summary": "final"}'
    assert api.extract_json(api.strip_think(reply))["summary"] == "final"
