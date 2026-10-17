"""Declared base extraction from submission notes."""
from __future__ import annotations

import re

_BASE = re.compile(r"[Bb]ase:(.*)")
_TOKEN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    r"|\b[0-9a-fA-F]{7,40}\b")


def declared_base_tokens(note: str) -> list[str]:
    """Candidate ids after "Base:" / "base:", in order of appearance.

    Accepts UUIDs, 40-hex SHAs and 7+ hex prefixes. A bare hex-looking word
    without a digit (e.g. "defaced") is ignored.
    """
    out: list[str] = []
    for line in (note or "").splitlines():
        m = _BASE.search(line)
        if not m:
            continue
        for t in _TOKEN.findall(m.group(1)):
            if "-" in t or len(t) == 40 or any(c.isdigit() for c in t):
                out.append(t)
    return out


def declared_base(note: str) -> str | None:
    toks = declared_base_tokens(note)
    return toks[0] if toks else None


def resolve(token: str, subs) -> str | None:
    """Map a token to a unique submission id via id prefix, commit_sha or promotedSourceRef."""
    t = token.lower()
    hits: set[str] = set()
    exact: set[str] = set()
    for s in subs:
        keys = [s.id, getattr(s, "commit_sha", None), getattr(s, "submission_sha", None),
                getattr(s, "promoted_ref", None)]
        for k in keys:
            if not k:
                continue
            k = k.lower()
            if k == t:
                exact.add(s.id)
            if k.startswith(t):
                hits.add(s.id)
    if len(exact) == 1:
        return next(iter(exact))
    if len(hits) == 1:
        return next(iter(hits))
    return None
