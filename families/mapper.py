"""Pure lookups: model line to family, vendor keyword detection, harness line."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

TABLE_PATH = Path(__file__).resolve().parent / "table.yaml"


class UnmappedModel(Exception):
    """A model line is absent from families/table.yaml."""


# Vendor keyword rules. Matching is case-insensitive; a keyword must not sit
# inside a longer alphanumeric run, so "opus" does not match "opusx".
_RULES: dict[str, tuple[str, ...]] = {
    "Anthropic": ("claude", "anthropic", "opus", "sonnet", "haiku", "fable"),
    "OpenAI": ("gpt", "openai"),
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


_ALLOWED = frozenset({"Anthropic", "OpenAI", "Google", "xAI", "Moonshot", "MiniMax",
                      "Zhipu", "DeepSeek", "Alibaba", "Mistral", "Meta", "Multi",
                      "Unknown"})
_OTHER = re.compile(r"^Other:\S.*$")


def validate_table(path: Path = TABLE_PATH) -> dict[str, str]:
    """Load the table and raise ValueError on any value outside the family set."""
    data = yaml.safe_load(Path(path).read_text())
    strings = data.get("strings") if isinstance(data, dict) else None
    if not isinstance(strings, dict):
        raise ValueError(f"{path}: missing 'strings' mapping")
    for k, v in strings.items():
        if not isinstance(v, str) or not (v in _ALLOWED or _OTHER.match(v)):
            raise ValueError(f"{path}: invalid family {v!r} for {k!r}")
    return strings


_cache: dict = {}


def _table() -> dict[str, str]:
    st = TABLE_PATH.stat()
    key = (st.st_mtime_ns, st.st_size)
    if _cache.get("key") != key:
        _cache["table"] = validate_table(TABLE_PATH)
        _cache["key"] = key
    return _cache["table"]


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
