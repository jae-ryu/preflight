import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def _isolate_stats_ledger(tmp_path, monkeypatch):
    """Never let a test write to the repo's real crew-stats ledger."""
    monkeypatch.setenv("PREFLIGHT_STATS_LEDGER", str(tmp_path / "reviewer-stats.jsonl"))
