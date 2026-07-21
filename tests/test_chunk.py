"""Per-file map-reduce splitting: file grouping, max-chunk cap, skipped_files, merge/dedupe/caps."""
from preflight import chunk, crew


def _file(name, body_lines):
    hunk = "@@ -1,3 +1,3 @@\n" + "\n".join(f"+{l}" for l in body_lines)
    return f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n{hunk}\n"


# ---------- split_files ----------

def test_split_files_names_and_count():
    d = _file("a.py", ["x"]) + _file("b/c.py", ["y"]) + _file("d.py", ["z"])
    files = chunk.split_files(d)
    assert [f["name"] for f in files] == ["a.py", "b/c.py", "d.py"]
    assert all(f["text"].startswith("diff --git") for f in files)


# ---------- chunk_diff grouping ----------

def test_small_files_grouped_into_few_chunks():
    # Many tiny files should pack together, not explode into many chunks.
    d = "".join(_file(f"f{i}.py", ["x", "y"]) for i in range(20))
    chunks, skipped = chunk.chunk_diff(d, chunk_cap=20000, max_chunks=6)
    assert skipped == []
    assert len(chunks) == 1  # 20 tiny files fit comfortably in one 20k chunk
    # No file lost.
    for i in range(20):
        assert f"f{i}.py" in chunks[0]


def test_splits_when_over_chunk_cap():
    # Files that together exceed the cap must spread across multiple chunks.
    d = "".join(_file(f"f{i}.py", ["really long content line " * 20] * 20) for i in range(6))
    chunks, skipped = chunk.chunk_diff(d, chunk_cap=20000, max_chunks=6)
    assert len(chunks) > 1
    for ch in chunks:
        # Each chunk stays within cap (a lone oversized file is the only exception).
        assert len(ch) <= 20000 or ch.count("diff --git") == 1


def test_max_chunks_cap_skips_least_changed():
    # More big files than fit in max_chunks -> smallest get skipped.
    big = ["content line " * 30] * 60          # ~ big file
    small_body = ["x"]
    files = "".join(_file(f"big{i}.py", big) for i in range(3))
    files += _file("tiny.py", small_body)      # least-changed, should be skipped
    chunks, skipped = chunk.chunk_diff(files, chunk_cap=20000, max_chunks=2)
    assert len(chunks) <= 2
    assert "tiny.py" in skipped


def test_chunking_is_deterministic():
    d = "".join(_file(f"f{i}.py", ["a", "b", "c"]) for i in range(10))
    a = chunk.chunk_diff(d)
    b = chunk.chunk_diff(d)
    assert a == b


# ---------- merge_findings: concat, dedupe, re-sort, caps ----------

def _find(sev, where):
    return {"sev": sev, "where": where, "issue": "i", "say": "s"}


def test_merge_dedupes_identical_where():
    lists = [
        [_find("med", "a.py:1")],
        [_find("med", "a.py:1")],  # duplicate
        [_find("low", "b.py:2")],
    ]
    merged = crew.merge_findings(lists)
    wheres = sorted(f["where"] for f in merged)
    assert wheres == ["a.py:1", "b.py:2"]


def test_merge_dedupe_keeps_highest_severity():
    lists = [[_find("low", "a.py:1")], [_find("high", "a.py:1")]]
    merged = crew.merge_findings(lists)
    assert len(merged) == 1
    assert merged[0]["sev"] == "high"


def test_merge_caps_3_gating_5_nits():
    gating = [_find("high", f"g{i}.py:1") for i in range(6)]
    nits = [_find("med", f"n{i}.py:1") for i in range(9)]
    merged = crew.merge_findings([gating, nits])
    high = [f for f in merged if f["sev"] == "high"]
    low = [f for f in merged if f["sev"] != "high"]
    assert len(high) == 3
    assert len(low) == 5


def test_merge_resorts_by_severity():
    lists = [[_find("low", "a"), _find("high", "b"), _find("med", "c")]]
    merged = crew.merge_findings(lists)
    assert [f["sev"] for f in merged] == ["high", "med", "low"]
