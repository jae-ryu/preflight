<!-- preflight-council -->
## 🚀 Preflight council review

### 🟠 **HOLD** — not cleared yet

`█████████░░░░░░░░░░░`  **45/100** &nbsp;·&nbsp; goal **85**

> 🧑‍🚀 **Mission Control:** Build artifacts shipped as source, sockets leak, case-sensitive model check crashes every call. Not launch-ready.

<img src="https://raw.githubusercontent.com/jae-ryu/preflight/main/art/reactions/hold-rough.gif" alt="hold-rough" width="240" align="right" />

#### 🚧 Gating (4)

🔴 `CloudInfra/mcp-servers/bos/build/lib/modular_bos_mcp/omni_client.py:110` — validate_model compares the requested id against /v1/models with a case-sensitive ==, but the API returns lowercased ids, so every valid model is rejected and no request ever goes through
> 🔥 **Roaster:** You ask for Kimi-K2.6, API whispers back kimi-k2.6, your == says NOPE. Congrats, the client rejects 100% of real models. Lowercase both sides or use casefold().

🔴 `CloudInfra/mcp-servers/bos/build/lib/modular_bos_mcp/omni_client.py:64-70` — response.json() is called before checking status; on a 5xx that returns an HTML error page this throws JSONDecodeError and swallows the real upstream failure
> 🔥 **Roaster:** Server hands you an HTML tombstone, you shove it into json() and faceplant. Check the status code BEFORE you parse, or you'll debug the wrong corpse forever.

🔴 `CloudInfra/mcp-servers/bos/build/lib/*` — Source files committed under build/lib/ (setuptools artifacts) while BUILD.bazel expects src/; .gitignore omits build/
> 🦣 **Mammoth:** Code lives in build/lib/. That is build artifact, not source. BUILD.bazel looks for src/. .gitignore blind to build/.

🔴 `CloudInfra/mcp-servers/bos/build/lib/modular_bos_mcp/__main__.py:20-25` — OmniClient/httpx.AsyncClient returned by build_server is discarded and never closed, leaking TCP connections
> 🦣 **Mammoth:** _omni born but never dies. Leak sockets. Need try/finally or context manager to aclose.

<details>
<summary><b>🧹 Nits (5)</b> — collapsed, grouped by file</summary>

**`CloudInfra/mcp-servers/bos/BUILD.bazel`**

| Sev | Where | Note |
|:---:|:---|:---|
| ⚪ LOW | `CloudInfra/mcp-servers/bos/BUILD.bazel:35` | modular_py_binary server redundantly declares requirement(mcp) already transitively provided by :modular_bos_mcp |

**`CloudInfra/mcp-servers/bos/build/lib/modular_bos_mcp/config.py`**

| Sev | Where | Note |
|:---:|:---|:---|
| 🟡 MED | `CloudInfra/mcp-servers/bos/build/lib/modular_bos_mcp/config.py:52` | int(os.environ['OMNI_TIMEOUT']) runs at import time with no guard; a value like '30s' crashes the whole server on boot with a raw ValueError |
| 🟡 MED | `CloudInfra/mcp-servers/bos/build/lib/modular_bos_mcp/config.py:45` | Raises EnvironmentError (an OSError subclass) for missing config instead of ValueError or a domain-specific exception |

**`CloudInfra/mcp-servers/bos/build/lib/modular_bos_mcp/omni_client.py`**

| Sev | Where | Note |
|:---:|:---|:---|
| 🟡 MED | `CloudInfra/mcp-servers/bos/build/lib/modular_bos_mcp/omni_client.py:85-88` | Only catches httpx.HTTPStatusError; transport errors (timeout, connect, network) leak as raw httpx exceptions instead of OmniClientError |
| 🟡 MED | `CloudInfra/mcp-servers/bos/build/lib/modular_bos_mcp/omni_client.py:72-78` | list_topics and validate_model silently handle polymorphic API responses without comments explaining shape variance |

</details>

#### ⬆️ Raise the score

- [ ] Purge build/lib/ from git; move source to src/ and fix .gitignore so artifacts stay out
- [ ] Close the OmniClient/httpx.AsyncClient with a context manager or try/finally in __main__.py
- [ ] Fix validate_model's case-sensitive compare so real model IDs stop getting rejected

<sub>Diff truncated at file boundaries (111,888 bytes) to fit the review budget.</sub>

---
🚀 Preflight council · powered by Modular Cloud (Kimi K2.6 + Gemma 4 + FLUX.2)
