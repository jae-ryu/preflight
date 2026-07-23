"""preflight.tags: stable ids, required fields, graceful why() fallback."""

import re

from preflight import tags

KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def test_schema_version():
    assert tags.SCHEMA_VERSION == 1


def test_ids_unique_and_kebab():
    ids = [t.id for t in tags.iter_tags()]
    assert len(ids) == len(set(ids))
    for tid in ids:
        assert KEBAB.match(tid), tid


def test_seed_ids_present():
    # These ids are already in BigQuery — they must never disappear.
    expected = {
        "crash-blind-observability",
        "error-path-fidelity",
        "best-effort-side-effect",
        "wrong-exception-type",
        "exception-state-timing",
        "info-leak",
        "resource-leak",
        "concurrency",
        "transport-safety",
        "wire-format",
        "duplication",
        "missing-tests",
        "unverified-claim",
        "naming-mismatch",
        "build-artifact",
    }
    assert expected <= {t.id for t in tags.iter_tags()}


def test_every_tag_has_required_fields():
    for t in tags.iter_tags():
        assert t.label.strip()
        assert t.why.strip() and "\n" not in t.why  # one line
        assert t.default_sev in ("high", "med", "low")


def test_get_known_and_unknown():
    assert tags.get("resource-leak").label == "Resource leak"
    assert tags.get("no-such-tag") is None
    assert tags.get(None) is None
    assert tags.get("") is None


def test_why_falls_back_gracefully():
    assert "released" in tags.why("resource-leak")
    fallback = tags.why("made-up-by-the-model")
    assert fallback and fallback == tags.why(None)


def test_iteration_order_stable():
    ids = [t.id for t in tags.iter_tags()]
    assert ids[0] == "crash-blind-observability"
    assert ids == [t.id for t in tags.iter_tags()]
