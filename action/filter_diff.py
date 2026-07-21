#!/usr/bin/env python3
"""
filter_diff.py — read optional .council.yml and filter a unified diff by paths.

.council.yml (in the target repo root) is optional:
    goal: 85
    paths:
      - "src/"
      - "*.py"

- Prints the resolved goal to stderr as "goal=<n>" (one line) so the shell can read it.
- Writes the (optionally path-filtered) diff to stdout.
- If no .council.yml or no paths, the diff passes through unchanged.

Deliberately dependency-free: a tiny YAML subset parser (goal + paths list) so the
action needs no pip install of pyyaml.
"""
import fnmatch
import os
import re
import sys


def parse_council_yml(path, default_goal):
    goal = default_goal
    paths = []
    if not os.path.exists(path):
        return goal, paths
    in_paths = False
    with open(path) as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            m = re.match(r"\s*goal\s*:\s*(\d+)", line)
            if m:
                goal = int(m.group(1))
                in_paths = False
                continue
            if re.match(r"\s*paths\s*:\s*$", line):
                in_paths = True
                continue
            # inline list: paths: ["a", "b"]
            m = re.match(r"\s*paths\s*:\s*\[(.*)\]", line)
            if m:
                for item in m.group(1).split(","):
                    item = item.strip().strip("'\"")
                    if item:
                        paths.append(item)
                in_paths = False
                continue
            if in_paths:
                m = re.match(r"\s*-\s*(.+)", line)
                if m:
                    paths.append(m.group(1).strip().strip("'\""))
                else:
                    in_paths = False
    return goal, paths


def file_matches(filepath, patterns):
    for pat in patterns:
        if pat.endswith("/"):
            if filepath.startswith(pat) or filepath.startswith(pat.rstrip("/") + "/"):
                return True
        if fnmatch.fnmatch(filepath, pat):
            return True
        # treat bare dir/prefix without trailing slash
        if filepath.startswith(pat.rstrip("/") + "/"):
            return True
    return False


def filter_diff(diff, patterns):
    if not patterns:
        return diff
    out = []
    keep = True
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            # "diff --git a/path b/path"
            parts = line.split()
            path_b = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else ""
            path_a = parts[2][2:] if len(parts) >= 3 and parts[2].startswith("a/") else ""
            keep = file_matches(path_b, patterns) or file_matches(path_a, patterns)
        if keep:
            out.append(line)
    return "".join(out)


def main():
    council_path = sys.argv[1] if len(sys.argv) > 1 else ".council.yml"
    default_goal = int(sys.argv[2]) if len(sys.argv) > 2 else 85
    diff = sys.stdin.read()
    goal, patterns = parse_council_yml(council_path, default_goal)
    sys.stderr.write(f"goal={goal}\n")
    sys.stdout.write(filter_diff(diff, patterns))


if __name__ == "__main__":
    main()
