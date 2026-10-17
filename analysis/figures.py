"""Deterministic figures (PNG and PDF) and their data files, from results/*.json."""
from __future__ import annotations

import json
import math
from pathlib import Path

from analysis import study

RC = {"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "font.size": 9,
      "figure.dpi": 100, "savefig.dpi": 150, "axes.unicode_minus": False,
      "pdf.fonttype": 42, "pdf.compression": 0, "text.usetex": False}
PNG_META = {"Software": None}
PDF_META = {"Creator": None, "Producer": None, "CreationDate": None, "Title": None,
            "Author": None, "Subject": None, "Keywords": None}


def _load(root, name):
    p = Path(root) / "results" / f"{name}.json"
    return json.loads(p.read_text()) if p.is_file() else None


def forest_rows(conf) -> list:
    rows = []
    for name in sorted(conf["benchmarks"]):
        e = conf["benchmarks"][name]["estimate"]
        if e["log_or"] is None or e["se"] is None:
            continue
        rows.append({"label": name, "log_or": e["log_or"], "lo": e["log_or"] - 1.96 * e["se"],
                     "hi": e["log_or"] + 1.96 * e["se"]})
    p = conf.get("pooled")
    if p:
        rows.append({"label": "pooled", "log_or": p["log_or"], "lo": p["ci95"][0], "hi": p["ci95"][1]})
    return rows


def sensitivity_rows(sens) -> list:
    rows = []
    for k in sorted(sens["sensitivities"]):
        v = sens["sensitivities"][k]
        if "pooled" in v:
            p = v["pooled"]
            rows.append({"label": k, "log_or": p["log_or"], "lo": p["ci95"][0], "hi": p["ci95"][1]})
    return rows


def _forest(rows, margin, title, stem, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with matplotlib.rc_context(RC):
        fig, ax = plt.subplots(figsize=(6.4, 0.5 * len(rows) + 1.6))
        ys = list(range(len(rows)))[::-1]
        for y, r in zip(ys, rows):
            ax.plot([math.exp(r["lo"]), math.exp(r["hi"])], [y, y], color="black", lw=1.2)
            ax.plot([math.exp(r["log_or"])], [y], "s" if r["label"] == "pooled" else "o",
                    color="black", ms=5)
        ax.axvline(1.0, color="grey", lw=0.8)
        for m in margin:
            ax.axvline(m, color="grey", lw=0.8, ls="--")
        ax.set_xscale("log")
        ax.set_yticks(ys)
        ax.set_yticklabels([r["label"] for r in rows])
        ax.set_xlabel("odds ratio of promotion, cross-family against same-family")
        ax.set_title(title)
        fig.tight_layout()
        fig.savefig(out_dir / f"{stem}.png", format="png", metadata=PNG_META)
        fig.savefig(out_dir / f"{stem}.pdf", format="pdf", metadata=PDF_META)
        plt.close(fig)


def run(root=None) -> dict:
    root = study.guard(root)
    out_dir = Path(root) / "paper" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    conf = _load(root, "confirmatory")
    data = {}
    if conf:
        rows = forest_rows(conf)
        data["forest_primary"] = rows
        _forest(rows, conf["margin"], "Primary result by benchmark", "forest_primary", out_dir)
    sens = _load(root, "sensitivity")
    if sens and conf:
        rows = sensitivity_rows(sens)
        if rows:
            data["forest_sensitivity"] = rows
            _forest(rows, conf["margin"], "Sensitivity analyses (pooled)", "forest_sensitivity", out_dir)
    for k, v in data.items():
        study.dump({"rows": v}, out_dir / f"{k}.json")
    return data
