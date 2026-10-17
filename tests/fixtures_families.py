"""Fixtures for tests/test_families.py (Track B)."""

# AT2 golden cases from spec section 9: (model line, family).
GOLDEN = [
    ("GPT-5 Codex", "OpenAI"),
    ("Claude Opus 4.8 (1M context)", "Anthropic"),
    ("Kimi K3", "Moonshot"),
    ("Devin", "Unknown"),
    ("Astra", "Unknown"),
    ("Claude Opus 5.5 + GPT-6.1 Sol", "Multi"),
    ("Grok 4.6 + Kimi k3", "Multi"),
]

# vendors_in cases: (model line, expected frozenset of family names).
VENDORS = [
    ("GPT-5 Codex", {"OpenAI"}),
    ("Kimi K3", {"Moonshot"}),
    ("Grok 4.6", {"xAI"}),
    ("Claude Opus 5.5 + GPT-6.1 Sol", {"Anthropic", "OpenAI"}),
    ("Grok 4.6 + Kimi k3", {"xAI", "Moonshot"}),
    ("Claude Opus 5.5 / GPT-6.1", {"Anthropic", "OpenAI"}),
    ("Claude Opus 5.5 & GPT-6.1", {"Anthropic", "OpenAI"}),
    ("Claude Opus 5.5 and GPT-6.1", {"Anthropic", "OpenAI"}),
    ("Claude Opus 5.5, GPT-6.1", {"Anthropic", "OpenAI"}),
    ("claude opus 5.5 + gpt-6.1", {"Anthropic", "OpenAI"}),
    ("CLAUDE OPUS 5.5 + KIMI K3", {"Anthropic", "Moonshot"}),
    ("Claude Opus 5.5 + GPT-6.1 + Grok 4.6", {"Anthropic", "OpenAI", "xAI"}),
]

# One vendor, even though the string contains "/" or "+" or parentheses.
SINGLE_VENDOR = [
    ("GPT-5.6 Sol", "OpenAI"),
    ("Claude Opus 4.8 (1M context)", "Anthropic"),
    ("GPT-5.6/Sol", "OpenAI"),
    ("GPT-5 + Codex", "OpenAI"),
    ("Claude Opus 4.8 + Claude Sonnet 5", "Anthropic"),
]

# No vendor keyword at all.
NO_VENDOR = ["Devin", "Droid", "Composer", "Factory", "Astra", "benchmark",
             "Scikit-learn"]
