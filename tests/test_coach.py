"""Per-character coaching hook: env-var feedback appended to system prompts."""
from preflight import crew


def test_no_env_leaves_prompt_unchanged(monkeypatch):
    monkeypatch.delenv("PREFLIGHT_ROASTER_EXTRA", raising=False)
    assert crew.coach(crew.ROASTER_SYS, "roaster") == crew.ROASTER_SYS


def test_env_appends_coaching_block(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_ROASTER_EXTRA", "look harder at async paths")
    out = crew.coach(crew.ROASTER_SYS, "roaster")
    assert out.startswith(crew.ROASTER_SYS)
    assert "COACHING FOR THIS RUN" in out
    assert "async paths" in out


def test_each_character_reads_its_own_var(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_MAMMOTH_EXTRA", "mammoth note")
    monkeypatch.setenv("PREFLIGHT_MC_EXTRA", "mc note")
    assert "mammoth note" in crew.coach(crew.MAMMOTH_SYS, "mammoth")
    assert "mc note" in crew.coach(crew.MC_SYS, "mission-control")
    # Roaster has no var set -> unchanged.
    monkeypatch.delenv("PREFLIGHT_ROASTER_EXTRA", raising=False)
    assert crew.coach(crew.ROASTER_SYS, "roaster") == crew.ROASTER_SYS


def test_blank_env_is_ignored(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_MC_EXTRA", "   ")
    assert crew.coach(crew.MC_SYS, "mission-control") == crew.MC_SYS
