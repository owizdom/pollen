"""Propose families for model lines and extend families/table.yaml.

Re-runnable: existing entries are never changed, only new strings are added.
Run `uv run python -m families.build_table` after the snapshot grows.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from families.mapper import TABLE_PATH, vendors_in  # noqa: E402
from snapshot.load import DEFAULT_ROOT, parse_model_line  # noqa: E402


# Strings from spec section 9 and the spec section 3.2 Unknown examples. They
# are always in the table so the golden cases hold before the live benchmarks
# (ecdsa.fail) are frozen.
SEED_LINES = [
    "GPT-5 Codex", "Claude Opus 4.8 (1M context)", "Kimi K3", "Kimi k3",
    "Claude Opus 5.5 + GPT-6.1 Sol", "Grok 4.6 + Kimi k3",
    "Devin", "Droid", "Composer", "Factory", "Astra", "benchmark",
    "Scikit-learn",
]


def _rule_family(line: str) -> str:
    v = vendors_in(line)
    if len(v) >= 2:
        return "Multi"
    if len(v) == 1:
        return next(iter(v))
    return "Unknown"


def propose(lines, existing: dict[str, str]) -> dict[str, str]:
    """existing plus rule-based entries for strings not yet present. Pure."""
    out = dict(existing)
    for line in lines:
        if line not in out:
            out[line] = _rule_family(line)
    return out


_SEP = re.compile(r"[+/&,]|\s(?:and|with|via)\s", re.IGNORECASE)


def review_list(strings, table: dict[str, str]) -> list[str]:
    """Strings with a separator that still resolve to fewer than two vendors."""
    return [s for s in strings if _SEP.search(s) and len(vendors_in(s)) < 2]


def snapshot_model_lines(root: Path = DEFAULT_ROOT) -> list[str]:
    """Distinct model lines in every benchmark directory present under root.

    Reads submissions.json.gz directly so it works before FREEZE.json exists.
    """
    lines: set[str] = set()
    for d in sorted(Path(root).iterdir()):
        p = d / "submissions.json.gz"
        if not p.exists():
            continue
        with gzip.open(p, "rb") as f:
            data = json.loads(f.read())
        for r in (data["submissions"] if isinstance(data, dict) else data):
            m = parse_model_line(r.get("note"))
            if m:
                lines.add(m)
    return sorted(lines)


def main(root: Path = DEFAULT_ROOT, table: Path = TABLE_PATH) -> None:
    existing = {}
    if table.exists():
        existing = (yaml.safe_load(table.read_text()) or {}).get("strings", {})
    merged = propose(SEED_LINES + snapshot_model_lines(root), existing)
    new = [k for k in merged if k not in existing]
    # Append-only: the file's existing text, comments included, is left as is.
    text = table.read_text() if table.exists() else "strings:\n"
    if text and not text.endswith("\n"):
        text += "\n"
    add = {k: merged[k] for k in new}
    if add:
        dumped = yaml.safe_dump(add, sort_keys=False, allow_unicode=True, width=1000)
        text += "".join("  " + ln + "\n" for ln in dumped.splitlines())
    table.write_text(text)
    print(f"{len(existing)} existing kept, {len(new)} added, {len(merged)} total")
    for k in new:
        if merged[k] == "Unknown":
            print(f"unresolved (Unknown): {k!r}")
    for k in review_list(merged, merged):
        print(f"review (separator, under two vendors): {k!r} -> {merged[k]}")


if __name__ == "__main__":
    main()
