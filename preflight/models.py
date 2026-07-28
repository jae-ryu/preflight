"""
models.py — task→model resolution for the council (Preflight is one mcloud app).

Which model runs which task is NOT hardcoded at the call sites. Each task
resolves from the environment, falling back to a sensible default, so the choice
can be driven by the shared BOS Modular Cloud registry (`bos_handlers.mcloud`) —
the gateway that polls what is *live* and records what each model is good for —
without Preflight taking a dependency on it or losing its stdlib-only footprint.
Preflight is just one application of Modular Cloud; the registry is the owner.

Task → crew mapping (task names mirror the shared registry's):
  reasoning — the reviewers (🔥 Roaster, 🦣 Mammoth): deep correctness/design.
  fast      — the overseer (🧑‍🚀 Mission Control) + chunk-summary: quick judging.

Resolution precedence (highest wins):
  PREFLIGHT_REVIEWER_MODEL / PREFLIGHT_OVERSEER_MODEL   (explicit, legacy names)
  PREFLIGHT_REASONING_MODEL / PREFLIGHT_FAST_MODEL      (task names)
  built-in DEFAULT_MODELS (below)
"""

import os

TASK_REASONING = "reasoning"
TASK_FAST = "fast"

# Built-in defaults. These are the last resort so a bare `preflight` still runs;
# a launcher wired to the shared registry can export the env vars below to steer
# task→model without editing anything here.
DEFAULT_MODELS = {
    TASK_REASONING: "moonshotai/kimi-k2.6",
    TASK_FAST: "google/gemma-4-31b-it",
}

_TASK_ENV = {
    TASK_REASONING: "PREFLIGHT_REASONING_MODEL",
    TASK_FAST: "PREFLIGHT_FAST_MODEL",
}


def _env(name):
    return (os.environ.get(name) or "").strip()


def model_for(task):
    """Resolve a task to a model id: the task env var, else the built-in default."""
    return _env(_TASK_ENV[task]) or DEFAULT_MODELS[task]


def reviewer_model():
    """Model for the reviewers (reasoning task). Honors the legacy override."""
    return _env("PREFLIGHT_REVIEWER_MODEL") or model_for(TASK_REASONING)


def overseer_model():
    """Model for the overseer + summary compression (fast task)."""
    return _env("PREFLIGHT_OVERSEER_MODEL") or model_for(TASK_FAST)
