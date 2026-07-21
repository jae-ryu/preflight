"""
Modular Cloud (MCloud) HTTP client + robust JSON extraction for reasoning models.

MCloud is OpenAI-compatible. Chat lives at POST /v1/chat/completions with an
`Authorization: Bearer $MODULAR_API_KEY` header.

Kimi K2.6 is a *reasoning* model: the response `message` carries BOTH `content`
and `reasoning_content`, and `usage.completion_tokens_details.reasoning_tokens`
burns ~6-8k tokens BEFORE the answer. If max_tokens is too small the whole budget
is spent thinking and `content` comes back empty. We therefore budget big
(max_tokens=20000) and parse defensively:

    1. JSON out of `content`
    2. else JSON out of `reasoning_content`
    3. else ONE repair-retry asking the model to re-emit ONLY the JSON object.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

API_URL = "https://api.modular.com/v1/chat/completions"

REVIEWER_MODEL = "moonshotai/Kimi-K2.6"      # reasoning — the reviewers
OVERSEER_MODEL = "google/gemma-4-31B-it"     # fast — the overseer

# Reasoning models spend the token budget thinking before they answer; budget big.
REVIEWER_MAX_TOKENS = 20000
OVERSEER_MAX_TOKENS = 1500


def api_key():
    return os.environ.get("MODULAR_API_KEY", "").strip()


class APIError(RuntimeError):
    """Raised when the MCloud endpoint is unreachable after retries."""


def _http_post(url, payload, timeout=300, retries=3, backoff=2.0):
    """Low-level POST returning the parsed JSON body. Retries transient failures.

    Isolated so tests can monkeypatch a single seam.
    """
    data = json.dumps(payload).encode()
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Authorization": f"Bearer {api_key()}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:500]
            except Exception:
                pass
            last_err = APIError(f"HTTP {e.code} from MCloud: {body}")
            # Retry only server-side / rate-limit errors.
            if e.code < 500 and e.code != 429:
                raise last_err
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = APIError(f"network error talking to MCloud: {e}")
        if attempt < retries - 1:
            time.sleep(backoff * (attempt + 1))
    raise last_err if last_err else APIError("unknown MCloud failure")


def post_chat(model, system, user, max_tokens, temperature=0.4):
    """One chat completion. Returns the full OpenAI-shaped response dict."""
    payload = {
        "model": model,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    return _http_post(API_URL, payload)


def extract_json(text):
    """Pull the first balanced JSON object out of a model reply.

    Tolerates code fences, leading/trailing prose, and braces inside strings.
    Returns the parsed dict/list, or None if nothing valid is found.
    """
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(start, len(t)):
        c = t[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:j + 1])
                except Exception:
                    return None
    return None  # unbalanced (e.g. truncated JSON)


def _message_of(resp):
    return resp["choices"][0]["message"]


def council_call(model, system, user, max_tokens):
    """Call a model expecting a JSON object back. Returns (data, parse_ok).

    Parse order: content -> reasoning_content -> one repair-retry.
    Raises APIError if the endpoint is unreachable.
    """
    resp = post_chat(model, system, user, max_tokens)
    msg = _message_of(resp)

    data = extract_json(msg.get("content") or "")
    if data is not None:
        return data, True

    data = extract_json(msg.get("reasoning_content") or "")
    if data is not None:
        return data, True

    # One repair-retry: force the model to re-emit ONLY the JSON object.
    repair = (user + "\n\nYour previous reply did not contain a valid JSON object. "
              "Re-emit ONLY the JSON object now, with no prose, no markdown, no code fences.")
    resp2 = post_chat(model, system, repair, max_tokens)
    msg2 = _message_of(resp2)
    data = (extract_json(msg2.get("content") or "")
            or extract_json(msg2.get("reasoning_content") or ""))
    if data is not None:
        return data, True
    return None, False
