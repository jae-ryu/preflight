"""Failure-class taxonomy for Preflight findings.

This module is the single source of truth for the finding "tag" attribute:
a small, versioned, append-only vocabulary of failure classes. Tag ids are
stable kebab-case strings that flow verbatim into `raw_bos_observability`
as BigQuery attribute values, where they power recurrence analysis (which
classes keep showing up across PRs) and auto-graduation of chronic classes
into the crew charter. Because downstream data keys on the id:

  - NEVER rename or delete an id. Only append new tags.
  - Bump SCHEMA_VERSION when the schema of a tag entry changes, not when a
    tag is added.

The taxonomy is deliberately iterable (``for tag in TAGS`` / ``iter_tags()``)
so reports, dashboards, and prompt charters can enumerate it without
hard-coding ids.
"""

from collections import OrderedDict
from dataclasses import dataclass

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Tag:
    id: str
    label: str
    why: str
    default_sev: str  # "high" | "med" | "low"


_SEED = [
    Tag(
        "crash-blind-observability",
        "Crash-blind observability",
        "Failures happen silently or with the wrong signal, so prod "
        "breakage is invisible until users report it.",
        "high",
    ),
    Tag(
        "error-path-fidelity",
        "Error-path fidelity",
        "The error path reports the wrong failure, so debugging chases "
        "the wrong corpse.",
        "high",
    ),
    Tag(
        "best-effort-side-effect",
        "Best-effort side effect",
        "A side effect can partially apply or silently skip, leaving "
        "state inconsistent with what callers believe.",
        "med",
    ),
    Tag(
        "wrong-exception-type",
        "Wrong exception type",
        "Callers catching by type will miss or over-catch, breaking "
        "error handling contracts downstream.",
        "med",
    ),
    Tag(
        "exception-state-timing",
        "Exception/state timing",
        "State is mutated before validation or raised after partial "
        "work, so exceptions leave corrupted state behind.",
        "high",
    ),
    Tag(
        "info-leak",
        "Information leak",
        "Secrets or internal details escape to logs, errors, or "
        "responses where they can be harvested.",
        "high",
    ),
    Tag(
        "resource-leak",
        "Resource leak",
        "Sockets, files, or handles are never released; the process "
        "degrades or exhausts limits under sustained load.",
        "high",
    ),
    Tag(
        "concurrency",
        "Concurrency",
        "Unsynchronized shared state races under real load, causing "
        "rare, hard-to-reproduce corruption.",
        "high",
    ),
    Tag(
        "transport-safety",
        "Transport safety",
        "Network failure modes (timeouts, retries, TLS) are unhandled, "
        "so transient faults become outages.",
        "high",
    ),
    Tag(
        "wire-format",
        "Wire format",
        "Serialized data disagrees with what the other side parses, "
        "breaking integrations at runtime, not compile time.",
        "high",
    ),
    Tag(
        "logic-error",
        "Logic error",
        "The code computes the wrong answer on valid input; correctness "
        "is broken even on the happy path.",
        "high",
    ),
    Tag(
        "input-validation",
        "Input validation",
        "Untrusted or malformed input reaches logic unchecked, causing "
        "crashes or exploitable behavior.",
        "high",
    ),
    Tag(
        "duplication",
        "Duplication",
        "Copies of the same logic drift apart, so a fix in one place "
        "leaves the bug alive elsewhere.",
        "med",
    ),
    Tag(
        "missing-tests",
        "Missing tests",
        "The changed behavior has no test, so regressions ship undetected.",
        "med",
    ),
    Tag(
        "unverified-claim",
        "Unverified claim",
        "The PR asserts behavior (perf, compatibility, safety) with no "
        "evidence, so reviewers approve on faith.",
        "med",
    ),
    Tag(
        "naming-mismatch",
        "Naming mismatch",
        "The name promises one behavior and the code does another, "
        "misleading every future reader and caller.",
        "low",
    ),
    Tag(
        "build-artifact",
        "Build artifact",
        "Generated or build output is committed as source, so edits go "
        "to files the build will overwrite or ignore.",
        "med",
    ),
    Tag(
        "dead-code",
        "Dead code",
        "Unreachable or unused code accretes, hiding real logic and "
        "inviting edits that do nothing.",
        "low",
    ),
    Tag(
        "wrong-abstraction",
        "Wrong abstraction",
        "The change solves the problem in the wrong place or shape; a "
        "simpler or better-located design would age far better.",
        "med",
    ),
    Tag(
        "over-engineered",
        "Over-engineered",
        "The change adds structure the problem does not warrant, paying "
        "complexity now for flexibility that may never be needed.",
        "low",
    ),
]

TAGS: "OrderedDict[str, Tag]" = OrderedDict((t.id, t) for t in _SEED)

# Fallback bucket for findings whose class is unknown or absent.
OTHER_ID = "other"
_OTHER = Tag(
    OTHER_ID,
    "Other",
    "Unclassified finding; review individually.",
    "med",
)


def iter_tags():
    """Iterate all known tags in stable seed order."""
    return iter(TAGS.values())


def get(tag_id):
    """Return the Tag for ``tag_id``, or None if unknown/absent."""
    if not tag_id:
        return None
    return TAGS.get(tag_id)


def why(tag_id):
    """One-line impact statement for ``tag_id``.

    Unknown or absent ids fall back to the generic 'other' line rather
    than raising, so renderers never crash on a tag the model invented.
    """
    tag = get(tag_id)
    return (tag or _OTHER).why
