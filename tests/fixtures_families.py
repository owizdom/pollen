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

# Review-driven golden labels (checked-in table).
GOLDEN_EXTRA = [
    ("Daybreak Blue", "OpenAI"),
    ("gpt-daybreak-blue-latest", "OpenAI"),
    ("Codex", "Unknown"),
    ("Codex CLI", "Unknown"),
    ("SWE-2 Max", "Other:Cognition"),
    ("Composer 2.5", "Other:Cursor"),
]

ALLOWED_FAMILIES = {"Anthropic", "OpenAI", "Google", "xAI", "Moonshot", "MiniMax",
                    "Zhipu", "DeepSeek", "Alibaba", "Mistral", "Meta", "Multi",
                    "Unknown"}

# Separator present but fewer than two vendors resolve: a human must look.
REVIEW_YES = ["GPT 6 Astra + Daybreak Blue", "GPT-5 Codex / Codex CLI",
              "GPT-5 with Devin", "Kimi K3 via Droid", "GPT-5 and Astra",
              "Kimi K3, Composer 2.5 & Devin"]
# Either no separator, or two vendors resolved.
REVIEW_NO = ["Kimi K3", "Devin", "GPT-5.6 Sol", "Claude Opus 4.8 (1M context)",
             "Claude Opus 5.5 + GPT-6.1 Sol", "Grok 4.6 + Kimi k3"]
