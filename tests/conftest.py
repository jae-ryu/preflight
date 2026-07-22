import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def _isolate_stats_ledger(tmp_path, monkeypatch):
    """Never let a test write to the repo's real crew-stats ledger."""
    monkeypatch.setenv("PREFLIGHT_STATS_LEDGER", str(tmp_path / "reviewer-stats.jsonl"))


@pytest.fixture(autouse=True)
def _clear_coaching_env(monkeypatch):
    """Keep coaching out of the default test env so prompt-identity checks are
    deterministic (coach() rewrites the system prompt when these are set)."""
    for var in ("PREFLIGHT_ROASTER_EXTRA", "PREFLIGHT_MAMMOTH_EXTRA", "PREFLIGHT_MC_EXTRA"):
        monkeypatch.delenv(var, raising=False)
