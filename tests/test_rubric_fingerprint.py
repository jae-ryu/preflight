"""The rubric must be able to prove which version scored a run.

RUBRIC_VERSION is a manual integer. It only works if somebody remembers to
bump it, and forgetting is silent: old and new scores become incomparable and
the only symptom is a trend that bends for no visible reason. These tests
cover the derived fingerprint, which does not rely on anyone remembering.
"""

import preflight.rubric as rubric


def test_fingerprint_is_stable_across_calls():
    assert rubric.rubric_fingerprint() == rubric.rubric_fingerprint()


def test_fingerprint_is_short_and_hex():
    fp = rubric.rubric_fingerprint()
    assert len(fp) == 12
    int(fp, 16)  # raises if not hex


def test_every_scoring_constant_moves_the_fingerprint(monkeypatch):
    """A weight changed without a version bump must still be detectable.

    This is the whole point: if a constant can change the score but not the
    fingerprint, two incomparable runs will claim to share a rubric.
    """
    base = rubric.rubric_fingerprint()
    for const, bumped in (
        ("CLAMP_BAND", 6),
        ("DEDUCT_BLOCKER_CORRECTNESS", 13),
        ("DEDUCT_BLOCKER_DESIGN", 9),
        ("DEDUCT_NIT_MED", 4),
        ("DEDUCT_NIT_LOW", 2),
        ("NIT_CAP", 11),
        ("RUBRIC_VERSION", 2),
        ("RUBRIC_SEMVER", "0.2.0"),
    ):
        monkeypatch.setattr(rubric, const, bumped)
        assert rubric.rubric_fingerprint() != base, f"{const} does not affect the fingerprint"
        monkeypatch.undo()


def test_result_carries_version_semver_and_fingerprint():
    out = rubric.finalize(90, "GO", [], [], goal=85)
    for key in ("rubric_version", "rubric_semver", "rubric_fingerprint"):
        assert key in out, key
    assert out["rubric_semver"] == rubric.RUBRIC_SEMVER
    assert out["rubric_fingerprint"] == rubric.rubric_fingerprint()
