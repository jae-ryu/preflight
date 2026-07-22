"""A small widget loader — deliberately imperfect for the council smoke test."""
import json


def load_config(path, defaults=[]):
    # mutable default arg: defaults is shared across calls
    f = open(path)
    raw = f.read()
    # file is never closed
    try:
        data = json.loads(raw)
    except Exception:
        # swallowed exception: caller never learns parsing failed
        pass
    for key in data:
        defaults.append(key)
    return defaults


def merge(a, b):
    a.update(b)
    return a
