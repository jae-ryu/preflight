"""
config.py — the single source of Preflight's baked-in defaults + .council.yml.

Everything a run needs is pre-filled here so you can *just use it*: no config
file required. A repo may drop an optional `.council.yml` at its root to
override any of these; a CLI flag overrides that in turn.

Precedence (highest wins):   CLI flag  >  .council.yml  >  DEFAULTS (here)

Kept dependency-free (a tiny YAML subset: `goal` + `paths`) so nothing here
needs pyyaml — the same reason action/filter_diff.py stays stdlib-only.
"""
import fnmatch
import os
import re

from . import api
from .diffcap import DEFAULT_CAP

# ---- baked-in defaults (the "already configured at the top" settings) -------
DEFAULTS = {
    "goal": 85,                       # repo-owner target score, 0-100
    "cap": DEFAULT_CAP,               # single-pass diff budget before map-reduce
    "reviewer_model": api.REVIEWER_MODEL,
    "overseer_model": api.OVERSEER_MODEL,
    "art_base": "https://raw.githubusercontent.com/jae-ryu/preflight/main/art/reactions",
    "paths": [],                      # empty = review the whole diff
}

DEFAULT_GOAL = DEFAULTS["goal"]


class Config:
    """Resolved run settings. Start from DEFAULTS, layer .council.yml, then flags."""

    def __init__(self, **kw):
        merged = dict(DEFAULTS)
        merged.update({k: v for k, v in kw.items() if v is not None})
        self.goal = int(merged["goal"])
        self.cap = int(merged["cap"])
        self.art_base = merged["art_base"]
        self.paths = list(merged["paths"])

    def __repr__(self):
        return f"Config(goal={self.goal}, cap={self.cap}, paths={self.paths})"


def _parse_council_yml(path):
    """Read the optional .council.yml. Returns {} when absent/empty.

    Recognises just `goal: <int>` and a `paths:` list (block or inline). Unknown
    keys are ignored — this is a convenience overlay, not a schema.
    """
    if not path or not os.path.exists(path):
        return {}
    out = {}
    paths = []
    in_paths = False
    with open(path) as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            m = re.match(r"\s*goal\s*:\s*(\d+)", line)
            if m:
                out["goal"] = int(m.group(1))
                in_paths = False
                continue
            m = re.match(r"\s*paths\s*:\s*\[(.*)\]", line)  # inline list
            if m:
                for item in m.group(1).split(","):
                    item = item.strip().strip("'\"")
                    if item:
                        paths.append(item)
                in_paths = False
                continue
            if re.match(r"\s*paths\s*:\s*$", line):
                in_paths = True
                continue
            if in_paths:
                m = re.match(r"\s*-\s*(.+)", line)
                if m:
                    paths.append(m.group(1).strip().strip("'\""))
                else:
                    in_paths = False
    if paths:
        out["paths"] = paths
    return out


def load(council_yml=".council.yml", **overrides):
    """Build a Config: DEFAULTS <- .council.yml <- explicit overrides (CLI flags).

    ``overrides`` values that are None are ignored, so callers can pass argparse
    results straight through without stripping unset flags.
    """
    layered = dict(_parse_council_yml(council_yml))
    layered.update({k: v for k, v in overrides.items() if v is not None})
    return Config(**layered)


def _file_matches(filepath, patterns):
    for pat in patterns:
        if pat.endswith("/") and filepath.startswith(pat):
            return True
        if fnmatch.fnmatch(filepath, pat):
            return True
        if filepath.startswith(pat.rstrip("/") + "/"):
            return True
    return False


def filter_diff(diff, patterns):
    """Keep only the file sections whose path matches one of ``patterns``.

    Empty ``patterns`` returns the diff unchanged. Mirrors action/filter_diff.py
    so a local `preflight review` and the CI action scope diffs identically.
    """
    if not patterns:
        return diff
    out = []
    keep = True
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            parts = line.split()
            path_b = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else ""
            path_a = parts[2][2:] if len(parts) >= 3 and parts[2].startswith("a/") else ""
            keep = _file_matches(path_b, patterns) or _file_matches(path_a, patterns)
        if keep:
            out.append(line)
    return "".join(out)
