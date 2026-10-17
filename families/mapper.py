"""Pure lookups: model line to family, vendor keyword detection, harness line."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

TABLE_PATH = Path(__file__).resolve().parent / "table.yaml"


class UnmappedModel(Exception):
    """A model line is absent from families/table.yaml."""


# Vendor keyword rules. Matching is case-insensitive; a keyword must not sit
# inside a longer alphanumeric run, so "opus" does not match "opusx".
_RULES: dict[str, tuple[str, ...]] = {
    "Anthropic": ("claude", "anthropic", "opus", "sonnet", "haiku", "fable"),
    "OpenAI": ("gpt", "codex", "openai"),
    "Google": ("gemini", "gemma", "google"),
    "xAI": ("grok",),
    "Moonshot": ("kimi", "moonshot"),
    "MiniMax": ("minimax",),
    "Zhipu": ("glm", "z.ai", "zhipu"),
    "DeepSeek": ("deepseek",),
    "Alibaba": ("qwen",),
    "Mistral": ("mistral", "codestral", "devstral"),
    "Meta": ("muse", "llama"),
    "Other:Cognition": ("swe-1", "swe-2", "swe-3"),
}
_PATTERNS = {
    fam: re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])|(?<![a-z0-9])(?:%s)(?=\d)" % (
        "|".join(re.escape(k) for k in kws), "|".join(re.escape(k) for k in kws)),
        re.IGNORECASE)
    for fam, kws in _RULES.items()
}


def vendors_in(model_line: str | None) -> frozenset[str]:
    """Families whose keywords appear in the string (empty for products, junk, None)."""
    if not model_line:
        return frozenset()
    return frozenset(f for f, p in _PATTERNS.items() if p.search(model_line))


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    return yaml.safe_load(TABLE_PATH.read_text())["strings"]


def family_of(model_line: str | None) -> str:
    """Table lookup. None is Unknown; a string absent from the table raises."""
    if model_line is None:
        return "Unknown"
    try:
        return _table()[model_line]
    except KeyError:
        raise UnmappedModel(model_line) from None


_HARNESS = re.compile(r"^harness:(.*)$", re.IGNORECASE | re.MULTILINE)


def harness_of(note: str) -> str | None:
    m = _HARNESS.search(note or "")
    if not m:
        return None
    return m.group(1).strip() or None
