"""Smart diff truncation. Cap the diff to keep token/credit cost bounded, but
cut on FILE boundaries (`diff --git`) so we never send half a file — and if even
the first file overflows, cut on HUNK boundaries (`@@`) so we never cut mid-hunk."""
import re

DEFAULT_CAP = 24000

_FILE_SPLIT = re.compile(r"(?=^diff --git )", re.M)


def cap_diff(diff, limit=DEFAULT_CAP):
    """Return (capped_diff, truncated: bool). Original returned unchanged if it fits."""
    if len(diff) <= limit:
        return diff, False

    parts = _FILE_SPLIT.split(diff)
    out = []
    used = 0
    for part in parts:
        if not part:
            continue
        if used + len(part) > limit:
            break
        out.append(part)
        used += len(part)

    if out:
        return "".join(out), True

    # First file alone exceeds the cap: fall back to a hunk boundary.
    chunk = diff[:limit]
    idx = chunk.rfind("\n@@")
    if idx > 0:
        return chunk[:idx] + "\n", True
    return chunk, True
