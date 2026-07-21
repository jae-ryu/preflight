"""
Per-file map-reduce splitting for big diffs.

When a diff exceeds the single-pass cap we split it into per-file units and pack
them into chunks (grouping tiny files together, each chunk <= CHUNK_CAP chars),
capped at MAX_CHUNKS. If more files remain than fit, we keep the largest / most-
changed files and record the rest in skipped_files (surfaced in meta).

Each chunk is then reviewed in parallel by the same persona and the findings are
merged back in code (see crew.merge_findings).
"""
import re

CHUNK_CAP = 20000
MAX_CHUNKS = 6

_FILE_SPLIT = re.compile(r"(?=^diff --git )", re.M)
_FILE_NAME = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.M)


def split_files(diff):
    """Split a unified diff into per-file units.

    Returns a list of dicts: {"name": <path>, "text": <file diff incl. header>}.
    Any leading preamble before the first 'diff --git' is attached to the first file.
    """
    parts = [p for p in _FILE_SPLIT.split(diff) if p]
    files = []
    preamble = ""
    for part in parts:
        m = _FILE_NAME.search(part)
        if not m:
            # Content before the first file header — hold and prepend to file 1.
            preamble += part
            continue
        text = preamble + part
        preamble = ""
        files.append({"name": m.group(2), "text": text})
    if preamble and files:
        files[0]["text"] += preamble
    elif preamble and not files:
        files.append({"name": "(unknown)", "text": preamble})
    return files


def chunk_diff(diff, chunk_cap=CHUNK_CAP, max_chunks=MAX_CHUNKS):
    """Pack a big diff into <= max_chunks chunks of <= chunk_cap chars each.

    Grouping is first-fit-decreasing by file size, so tiny files share a chunk and
    the largest / most-changed files win a slot when we run out of room. Files that
    don't fit in max_chunks are dropped and returned in skipped_files.

    Returns (chunk_texts: list[str], skipped_files: list[str]).
    """
    files = split_files(diff)
    # Most-changed first, so the biggest files claim slots; ties broken by name for
    # deterministic output.
    files_sorted = sorted(files, key=lambda f: (-len(f["text"]), f["name"]))

    bins = []          # list of {"size": int, "files": [file dict, ...]}
    skipped = []
    for f in files_sorted:
        size = len(f["text"])
        placed = False
        for b in bins:
            if b["size"] + size <= chunk_cap:
                b["files"].append(f)
                b["size"] += size
                placed = True
                break
        if placed:
            continue
        if len(bins) < max_chunks:
            # New chunk (a single file larger than the cap still gets its own chunk).
            bins.append({"size": size, "files": [f]})
        else:
            skipped.append(f["name"])

    # Within each chunk, keep files in original diff order for readability.
    order = {f["name"]: i for i, f in enumerate(files)}
    chunk_texts = []
    for b in bins:
        b["files"].sort(key=lambda f: order.get(f["name"], 0))
        chunk_texts.append("".join(f["text"] for f in b["files"]))

    skipped.sort()
    return chunk_texts, skipped
