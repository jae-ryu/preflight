"""Smart diff truncation on file / hunk boundaries."""
from preflight.diffcap import cap_diff


def _file(name, body_lines):
    hunk = "@@ -1,3 +1,3 @@\n" + "\n".join(f"+{l}" for l in body_lines)
    return f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n{hunk}\n"


def test_small_diff_untouched():
    d = _file("a.py", ["x", "y"])
    out, trunc = cap_diff(d, limit=10000)
    assert out == d
    assert trunc is False


def test_truncates_on_file_boundary():
    f1 = _file("a.py", ["line"] * 5)
    f2 = _file("b.py", ["line"] * 5)
    f3 = _file("c.py", ["line"] * 5)
    d = f1 + f2 + f3
    limit = len(f1) + len(f2) + 5  # room for two files, not the third
    out, trunc = cap_diff(d, limit=limit)
    assert trunc is True
    assert out == f1 + f2
    # never cut mid-file: output ends cleanly at a file boundary
    assert "c.py" not in out


def test_first_file_too_big_falls_back_to_hunk_boundary():
    body = ["really long line of content " * 3] * 40
    big = _file("huge.py", body)
    assert len(big) > 500
    out, trunc = cap_diff(big, limit=300)
    assert trunc is True
    # Must not cut mid-hunk: no partial trailing hunk beyond a boundary.
    assert len(out) <= 300
