"""Analysis-row denominator (spec 0001 section 3.1)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "denominator.yaml"
KEPT_STATUSES = ("accepted", "rejected", "failed")


class UnclassifiedFailure(Exception):
    """A failed row's reason matches no entry of failure_classes."""


def load_config(path=None) -> dict:
    return yaml.safe_load(Path(path or CONFIG_PATH).read_text()) or {}


def _never_evaluated(reason, exact: set, patterns: list) -> bool:
    if not reason:
        return False
    return reason in exact or any(p.search(reason) for p in patterns)


def classify_failure(reason, classes: dict):
    """Class of a failure reason: exact key first, then regex search, else None."""
    if reason in classes:
        return classes[reason]
    for key, cls in classes.items():
        try:
            if re.search(key, reason):
                return cls
        except re.error:
            continue
    return None


def analysis_rows(subs, benchmark, config=None, drop_ambiguous=False):
    """Drop cancelled, non-final, never-scored and infrastructure-failure rows.

    Ambiguous failures are kept unless drop_ambiguous. A failed row with a
    reason matching no class raises UnclassifiedFailure.
    """
    cfg = load_config() if config is None else config
    exact = set(cfg.get("default") or []) | set((cfg.get("benchmarks") or {}).get(benchmark) or [])
    pats = [re.compile(p) for p in (cfg.get("default_regex") or [])]
    pats += [re.compile(p) for p in (cfg.get("benchmarks_regex") or {}).get(benchmark) or []]
    classes = cfg.get("failure_classes") or {}
    out = []
    for s in subs:
        if s.cancelled or s.status not in KEPT_STATUSES:
            continue
        if _never_evaluated(s.rejection_reason, exact, pats):
            continue
        if s.status == "failed" and s.rejection_reason:
            cls = classify_failure(s.rejection_reason, classes)
            if cls is None:
                raise UnclassifiedFailure(
                    f"{benchmark}: {s.id}: no failure class for {s.rejection_reason!r}")
            if cls == "infrastructure" or (cls == "ambiguous" and drop_ambiguous):
                continue
        out.append(s)
    return out
