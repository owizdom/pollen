"""Analysis-row denominator (spec 0001 section 3.1)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "denominator.yaml"


def load_config(path=None) -> dict:
    return yaml.safe_load(Path(path or CONFIG_PATH).read_text()) or {}


def _never_evaluated(reason, exact: set, patterns: list) -> bool:
    if not reason:
        return False
    return reason in exact or any(p.search(reason) for p in patterns)


def analysis_rows(subs, benchmark, config=None):
    """Drop cancelled rows and rows rejected without ever being scored."""
    cfg = load_config() if config is None else config
    exact = set(cfg.get("default") or []) | set((cfg.get("benchmarks") or {}).get(benchmark) or [])
    pats = [re.compile(p) for p in (cfg.get("default_regex") or [])]
    pats += [re.compile(p) for p in (cfg.get("benchmarks_regex") or {}).get(benchmark) or []]
    return [
        s for s in subs
        if not s.cancelled and not _never_evaluated(s.rejection_reason, exact, pats)
    ]
