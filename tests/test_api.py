"""JSON extraction + council_call parse ladder. API fully mocked."""
import json

import pytest

from preflight import api


# ---------- extract_json ----------

def test_clean_json():
    assert api.extract_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_fenced_json():
    text = '```json\n{"summary": "ok", "findings": []}\n```'
    assert api.extract_json(text) == {"summary": "ok", "findings": []}


def test_json_with_leading_prose():
    text = 'Sure! Here is the object:\n{"score": 62}\ntrailing chatter'
    assert api.extract_json(text) == {"score": 62}


def test_braces_inside_strings():
    text = '{"say": "close the } brace {", "sev": "high"}'
    assert api.extract_json(text) == {"say": "close the } brace {", "sev": "high"}


def test_truncated_json_returns_none():
    # Missing closing braces — unbalanced.
    text = '{"summary": "oops", "findings": [{"sev": "high",'
    assert api.extract_json(text) is None


def test_no_json_returns_none():
    assert api.extract_json("just prose, no object here") is None
    assert api.extract_json("") is None
    assert api.extract_json(None) is None


# ---------- council_call parse ladder ----------

def _resp(content=None, reasoning=None):
    return {"choices": [{"message": {
        "content": content or "",
        "reasoning_content": reasoning or "",
    }}]}


def _seq(monkeypatch, *responses):
    """Queue post_chat responses; record how many calls happened."""
    calls = {"n": 0}

    def fake_post_chat(model, system, user, max_tokens, temperature=0.4, node=None):
        i = calls["n"]
        calls["n"] += 1
        return responses[min(i, len(responses) - 1)]

    monkeypatch.setattr(api, "post_chat", fake_post_chat)
    return calls


def test_council_call_from_content(monkeypatch):
    calls = _seq(monkeypatch, _resp(content='{"summary": "clean", "findings": []}'))
    data, ok = api.council_call("m", "s", "u", 20000)
    assert ok is True
    assert data["summary"] == "clean"
    assert calls["n"] == 1  # no retry needed


def test_council_call_from_reasoning_content(monkeypatch):
    # content empty (reasoning ate the budget); JSON only in reasoning_content.
    calls = _seq(monkeypatch, _resp(content="", reasoning='thinking... {"summary": "r", "findings": []}'))
    data, ok = api.council_call("m", "s", "u", 20000)
    assert ok is True
    assert data["summary"] == "r"
    assert calls["n"] == 1  # found in reasoning, no repair retry


def test_council_call_empty_triggers_repair_retry(monkeypatch):
    # First response has nothing parseable anywhere; repair retry succeeds.
    calls = _seq(
        monkeypatch,
        _resp(content="", reasoning="pure thoughts, no json"),
        _resp(content='{"summary": "repaired", "findings": []}'),
    )
    data, ok = api.council_call("m", "s", "u", 20000)
    assert ok is True
    assert data["summary"] == "repaired"
    assert calls["n"] == 2  # original + one repair retry


def test_council_call_gives_up_after_repair(monkeypatch):
    calls = _seq(
        monkeypatch,
        _resp(content="nope"),
        _resp(content="still nope"),
    )
    data, ok = api.council_call("m", "s", "u", 20000)
    assert ok is False
    assert data is None
    assert calls["n"] == 2  # only one repair retry, then gives up


# ---------- run trace ----------

def _resp_usage(content, prompt=100, completion=1200, reasoning=6800):
    return {
        "choices": [{"message": {"content": content, "reasoning_content": ""}}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
        },
    }


def test_trace_captures_usage_when_present(monkeypatch):
    api.reset_trace()
    monkeypatch.setattr(api, "_http_post",
                        lambda url, payload, **kw: _resp_usage('{"summary": "ok", "findings": []}'))
    data, ok = api.council_call("m", "s", "u", 20000, node="roaster-c1")
    assert ok is True
    assert len(api.TRACE) == 1
    row = api.TRACE[0]
    assert row["node"] == "roaster-c1"
    assert row["usage"] == {"prompt_tokens": 100, "completion_tokens": 1200,
                            "reasoning_tokens": 6800}
    assert row["parse_ok"] is True
    assert row["duration_ms"] >= 0
    assert row["retries"] == 0


def test_trace_tolerates_missing_usage(monkeypatch):
    api.reset_trace()
    # No usage object at all — must fill zeros, never crash.
    monkeypatch.setattr(api, "_http_post",
                        lambda url, payload, **kw: _resp(content='{"summary": "ok", "findings": []}'))
    api.council_call("m", "s", "u", 20000, node="mammoth-c1")
    row = api.TRACE[0]
    assert row["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0}


def test_trace_records_repair_retry_row(monkeypatch):
    api.reset_trace()
    seq = [_resp(content="no json here"), _resp_usage('{"summary": "fixed", "findings": []}')]
    calls = {"n": 0}

    def fake(url, payload, **kw):
        r = seq[min(calls["n"], len(seq) - 1)]
        calls["n"] += 1
        return r

    monkeypatch.setattr(api, "_http_post", fake)
    data, ok = api.council_call("m", "s", "u", 20000, node="roaster-c1")
    assert ok is True
    assert [r["node"] for r in api.TRACE] == ["roaster-c1", "roaster-c1-repair"]
    assert api.TRACE[0]["parse_ok"] is False   # first call failed to parse
    assert api.TRACE[1]["parse_ok"] is True     # repair succeeded


def test_no_trace_row_without_node(monkeypatch):
    api.reset_trace()
    monkeypatch.setattr(api, "_http_post",
                        lambda url, payload, **kw: _resp(content='{"x": 1}'))
    api.council_call("m", "s", "u", 20000)  # no node
    assert api.TRACE == []


def test_post_chat_payload_shape(monkeypatch):
    captured = {}

    def fake_http_post(url, payload, **kw):
        captured["url"] = url
        captured["payload"] = payload
        return _resp(content="{}")

    monkeypatch.setattr(api, "_http_post", fake_http_post)
    api.post_chat("moonshotai/Kimi-K2.6", "sys", "user", 20000)
    assert captured["url"] == api.API_URL
    p = captured["payload"]
    assert p["model"] == "moonshotai/Kimi-K2.6"
    assert p["max_tokens"] == 20000
    assert p["messages"][0]["role"] == "system"
    assert p["messages"][1]["content"] == "user"
